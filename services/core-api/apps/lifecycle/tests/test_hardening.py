"""Regressions found by probing the lifecycle live: masking gaps, injection, ReDoS, stale tokens,
unchecked commits, drifting resolution stamps, 500s on crafted input, and dangling references."""

from __future__ import annotations

import json
import time
from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from apps.lifecycle.models import ActionRun, ApprovalRequest, SystemStatus, Workflow, WorkflowStatus
from apps.lifecycle.request_schema import (
    FieldIn,
    FieldPatch,
    RuleIn,
    StatusIn,
    StatusPatch,
    SystemStatusIn,
    SystemStatusPatch,
    TransitionPatch,
    WorkflowIn,
    WorkflowPatch,
)
from apps.lifecycle.tests.conftest import actions, put_in, status_of
from apps.lifecycle.utils.actions import callback_token
from apps.lifecycle.utils.config import KEY_LENGTH, workflow_config
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.fields import field_values
from apps.lifecycle.utils.rules import FieldType, RuleCode, accepts
from apps.lifecycle.utils.vocabulary import (
    FailureCode,
    PipelineStatus,
    RunState,
    TransferState,
    Trigger,
)
from apps.tickets.models import Ticket
from infrastructure.outbound import OutboundHttp, OutboundUnavailable

pytestmark = pytest.mark.django_db

BASE = "/api/lifecycle"
# Captured at import, before the autouse ai-engine fixture patches httpx.Client.
_REAL_CLIENT = httpx.Client


def refused(code: FailureCode):
    return pytest.raises(LifecycleError, match="") if code is None else _Refused(code)


class _Refused:
    def __init__(self, code: FailureCode) -> None:
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, kind, error, tb):
        assert isinstance(error, LifecycleError), f"expected {self.code}, got {error!r}"
        assert error.code is self.code, f"expected {self.code}, got {error.code}: {error.message}"
        return True


def reload(ticket: Ticket) -> Ticket:
    return Ticket.objects.get(pk=ticket.pk)


def before_action(strict, *items):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done), TransitionPatch(actions=actions(*items))
    )


# ── PII ──


def test_a_user_field_refuses_free_text_and_takes_a_username(ticket, technician_user):
    field = workflow_config.add_field(
        Workflow.objects.default(), FieldIn(name="Owner", field_type=FieldType.USER)
    )

    with refused(FailureCode.INVALID_FIELD_VALUE):
        field_values.write(
            ticket.id, {field.id: "john@corp.example 0912345678"}, actor=technician_user
        )
    field_values.write(ticket.id, {field.id: technician_user.username}, actor=technician_user)

    assert field_values.by_name(ticket) == {"Owner": technician_user.username}


# ── injection ──


def test_a_placeholder_cannot_add_keys_to_a_webhook_body(ticket, strict, celery, webhooks):
    Ticket.objects.filter(pk=ticket.pk).update(subject_masked='x", "admin": true, "z": "')
    before_action(
        strict,
        {
            "action": "call_webhook",
            "params": {
                "url": "http://localhost/hook",
                "body": '{"subject": "{{ticket.subject}}", "admin": false}',
            },
            "position": "before",
        },
    )
    put_in(ticket, strict.working)

    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()

    assert webhooks.calls[0]["body"] == {"subject": 'x", "admin": true, "z": "', "admin": False}


def test_a_body_template_with_a_bare_placeholder_is_refused(strict):
    with refused(FailureCode.INVALID_CONFIG):
        before_action(
            strict,
            {
                "action": "call_webhook",
                "params": {"url": "http://localhost/hook", "body": '{"n": {{field.Count}}}'},
                "position": "before",
            },
        )


# ── ReDoS ──


def test_a_catastrophic_pattern_fails_fast_instead_of_hanging(ticket, strict, technician_user):
    field = workflow_config.add_field(
        strict.workflow, FieldIn(name="Code", field_type=FieldType.TEXT)
    )
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            rules=[RuleIn(field_id=field.id, rule=RuleCode.PATTERN, params={"pattern": "(a+)+$"})]
        ),
    )
    put_in(ticket, strict.working)
    field_values.write_by_name(ticket, {"Code": "a" * 40 + "!"}, depth=0)

    started = time.monotonic()
    with refused(FailureCode.RULE_VIOLATION):
        lifecycle.move(
            ticket.id, strict.done.id, actor=technician_user, force=False, expected_version=None
        )

    assert time.monotonic() - started < 2


# ── retries and callbacks ──


def n8n_before(strict):
    before_action(
        strict,
        {
            "action": "trigger_n8n",
            "params": {"webhook_url": "http://localhost/n8n"},
            "position": "before",
        },
    )


def test_a_retried_run_gets_a_new_callback_token(ticket, strict, celery, webhooks, technician_user):
    n8n_before(strict)
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()
    run = ActionRun.objects.get(transfer__ticket=ticket)
    first = webhooks.calls[0]["body"]["callbackToken"]
    lifecycle.complete_callback(run.id, token=first, success=False, message="no", output=None)
    celery.drain()

    lifecycle.retry(ticket.id, technician_user)
    celery.drain()

    second = webhooks.calls[1]["body"]["callbackToken"]
    assert second != first
    with refused(FailureCode.BAD_CALLBACK_TOKEN):
        lifecycle.complete_callback(run.id, token=first, success=True, message="", output=None)


def test_retry_is_refused_while_an_action_is_still_waiting(
    ticket, strict, celery, webhooks, technician_user
):
    n8n_before(strict)
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()

    with refused(FailureCode.TRANSFER_IN_PROGRESS):
        lifecycle.retry(ticket.id, technician_user)

    assert len(webhooks.calls) == 1


def test_an_unknown_run_or_approval_is_a_404_not_a_500(client, api_as, manager_user, ticket):
    import uuid

    missing = uuid.uuid4()
    callback = client.post(
        f"{BASE}/action-runs/{missing}/callback",
        json.dumps({"success": True}),
        content_type="application/json",
        HTTP_X_LIFECYCLE_TOKEN="x",
    )
    approve = api_as(manager_user).post(
        f"{BASE}/approvals/{missing}/approve", "{}", content_type="application/json"
    )
    change = api_as(manager_user).post(
        f"{BASE}/tickets/{ticket.public_id}/change-workflow",
        json.dumps({"status_id": str(missing)}),
        content_type="application/json",
    )

    assert [r.status_code for r in (callback, approve, change)] == [404, 404, 404]
    assert {r.json()["code"] for r in (callback, approve, change)} == {"not_found"}


# ── rules at commit ──


def test_a_rule_broken_while_a_move_waited_stops_the_commit(
    ticket, strict, celery, manager_user, technician_user
):
    field = workflow_config.add_field(
        strict.workflow, FieldIn(name="Tested", field_type=FieldType.CHECKBOX)
    )
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            rules=[RuleIn(field_id=field.id, rule=RuleCode.MUST_BE_CHECKED)],
            actions=actions(
                {
                    "action": "require_approval",
                    "params": {"approvers": manager_user.username},
                    "position": "before",
                }
            ),
        ),
    )
    put_in(ticket, strict.working)
    field_values.write_by_name(ticket, {"Tested": True}, depth=0)
    lifecycle.move(
        ticket.id, strict.done.id, actor=technician_user, force=False, expected_version=None
    )
    celery.drain()
    field_values.write_by_name(ticket, {"Tested": False}, depth=0)

    approval = ApprovalRequest.objects.get(run__ticket=ticket)
    lifecycle.decide_approval(approval.id, user=manager_user, approve=True, comment="")
    celery.drain()

    assert reload(ticket).status == strict.working.key
    transfer = ticket.transfers.latest("created_at")
    assert transfer.state == TransferState.FAILED.value
    assert transfer.failure_code == FailureCode.RULE_VIOLATION.value


# ── resolved_at ──


def test_rebasing_a_status_onto_a_completed_stage_stamps_its_tickets(ticket, strict):
    put_in(ticket, strict.working)
    resolved = SystemStatus.objects.get(name="Resolved")

    workflow_config.update_status(strict.working, StatusPatch(base_id=resolved.id))
    assert reload(ticket).resolved_at is not None

    workflow_config.update_status(strict.working, StatusPatch(base_id=strict.hold.base.id))
    assert reload(ticket).resolved_at is None


def test_marking_a_stage_completed_stamps_tickets_already_in_it(ticket, strict):
    stage = workflow_config.create_system_status(SystemStatusIn(name="Parked", color="#123456"))
    parked = workflow_config.add_status(strict.workflow, StatusIn(name="Parked", base_id=stage.id))
    put_in(ticket, parked)

    workflow_config.update_system_status(stage, SystemStatusPatch(is_completed=True))

    assert reload(ticket).resolved_at is not None


def test_a_pipeline_status_keeps_whether_it_counts_as_resolved(strict):
    resolved = SystemStatus.objects.get(name="Resolved")

    with refused(FailureCode.PIPELINE_STATUS_LOCKED):
        workflow_config.update_status(strict.review, StatusPatch(base_id=resolved.id))
    with refused(FailureCode.PIPELINE_STATUS_LOCKED):
        workflow_config.update_system_status(
            strict.review.base, SystemStatusPatch(is_completed=True)
        )


# ── crafted input ──


def test_null_in_a_patch_leaves_the_field_alone(strict):
    stage = strict.working.base
    workflow_config.update_system_status(
        stage, SystemStatusPatch.model_validate({"name": None, "order": None})
    )

    stage.refresh_from_db()
    assert stage.name == "In progress"


@pytest.mark.parametrize("body", ['{"x": NaN, "y": 0}', '{"x": 1e308, "y": 0}'])
def test_an_unbounded_coordinate_is_refused(api_as, manager_user, strict, body):
    response = api_as(manager_user).post(
        f"{BASE}/statuses/{strict.working.id}/position", body, content_type="application/json"
    )

    assert response.status_code == 422


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 10**400])
def test_a_non_finite_or_huge_number_is_not_a_number_value(value):
    assert not accepts(FieldType.NUMBER, value, [])


def test_a_nul_character_is_refused(api_as, manager_user):
    response = api_as(manager_user).post(
        f"{BASE}/workflows", json.dumps({"name": "bad\u0000name"}), content_type="application/json"
    )

    assert response.status_code == 422


def test_a_lost_uniqueness_race_is_a_409(monkeypatch, manager_user):
    monkeypatch.setattr(workflow_config, "check_name_free", lambda others, name: None)

    with refused(FailureCode.NAME_TAKEN):
        workflow_config.create_workflow(WorkflowIn(name="Default"), actor=manager_user)


def test_a_status_key_always_fits_the_status_column(strict):
    stem = "abcdefghijklmnopqrs"
    WorkflowStatus.objects.bulk_create(
        WorkflowStatus(
            workflow=strict.workflow,
            base=strict.working.base,
            key=(stem[:KEY_LENGTH] if n == 1 else stem[: KEY_LENGTH - len(f"_{n}")] + f"_{n}"),
            name=f"filler {n}",
            color="#000000",
        )
        for n in range(1, 101)
    )

    key = workflow_config.new_key(strict.workflow, stem)

    assert len(key) <= KEY_LENGTH
    assert not strict.workflow.statuses.filter(key=key).exists()


def test_vietnamese_d_survives_in_a_status_key(strict):
    status = workflow_config.add_status(
        strict.workflow, StatusIn(name="Đang xử lý", base_id=strict.working.base.id)
    )

    assert status.key == "dang_xu_ly"


# ── webhook timing ──


def test_a_trickling_answer_is_cut_at_the_total_timeout(settings, monkeypatch):
    settings.LIFECYCLE_WEBHOOK_ALLOWED_HOSTS = ["hooks.example.com"]
    settings.LIFECYCLE_HTTP_TOTAL_TIMEOUT_SEC = 0.05
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )

    def drip():
        for _ in range(5):
            time.sleep(0.03)
            yield b"x"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=drip()))

    class Stub(_REAL_CLIENT):
        def __init__(self, *a, **kw):
            super().__init__(*a, **{**kw, "transport": transport})

    monkeypatch.setattr("infrastructure.outbound.httpx.Client", Stub)

    with pytest.raises(OutboundUnavailable, match="total timeout"):
        OutboundHttp().send("https://hooks.example.com/x", method="POST")


# ── workflow changes ──


def test_change_workflow_within_the_same_workflow_is_refused(ticket, strict, manager_user):
    put_in(ticket, strict.working)

    with refused(FailureCode.SAME_WORKFLOW):
        lifecycle.change_workflow(ticket.id, strict.done.id, actor=manager_user)


def test_adopting_a_workflow_into_itself_is_refused(strict, manager_user):
    with refused(FailureCode.SAME_WORKFLOW):
        lifecycle.adopt_tickets(strict.workflow, strict.workflow, {}, actor=manager_user)


# ── cancellation ──


def test_a_run_cancelled_mid_flight_is_not_marked_succeeded(ticket, strict, celery, webhooks):
    before_action(
        strict,
        {
            "action": "call_webhook",
            "params": {"url": "http://localhost/hook"},
            "position": "before",
        },
    )
    put_in(ticket, strict.working)
    original = webhooks.send

    def send_while_the_pipeline_moves(url, *, method, json_body=None):
        lifecycle.system_move(Ticket.objects.get(pk=ticket.pk), PipelineStatus.REOPENED)
        return original(url, method=method, json_body=json_body)

    webhooks.send = send_while_the_pipeline_moves
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()

    run = ActionRun.objects.get(transfer__ticket=ticket)
    assert run.state == RunState.SKIPPED.value
    assert reload(ticket).status == "reopened"


# ── configuration hygiene ──


def test_names_are_unique_ignoring_case_and_spaces(manager_user):
    with refused(FailureCode.NAME_TAKEN):
        workflow_config.create_workflow(WorkflowIn(name="  default "), actor=manager_user)


@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("assign_team", {"team": "{{ticket.nonexistent}}"}),
        ("call_webhook", {"url": "http://evil.example.net/x"}),
        ("call_webhook", {"url": "http://localhost:99999/x"}),
        ("send_email", {"to": "not-an-address", "subject": "s", "body": "b"}),
        ("send_email", {"to": "a@example.com", "subject": "two\nlines", "body": "b"}),
        ("set_sla", {"business_hours": 1e300, "reason": "contract"}),
        ("set_sla", {"business_hours": 4}),
        ("set_sla", {"offset_hours": 4, "reason": "old wall-clock form"}),
    ],
)
def test_an_action_that_can_never_work_is_refused_when_saved(strict, action, params):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.update_status(
            strict.done, StatusPatch(actions=actions({"action": action, "params": params}))
        )


def test_a_set_field_value_of_the_wrong_type_is_refused_when_saved(strict):
    workflow_config.add_field(strict.workflow, FieldIn(name="Cost", field_type=FieldType.NUMBER))

    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.update_status(
            strict.done,
            StatusPatch(
                actions=actions(
                    {"action": "set_field", "params": {"field": "Cost", "value": "lots"}}
                )
            ),
        )


def test_an_employee_cannot_be_an_approver(strict, employee_user):
    with refused(FailureCode.INVALID_CONFIG):
        before_action(
            strict,
            {
                "action": "require_approval",
                "params": {"approvers": employee_user.username},
                "position": "before",
            },
        )


def test_a_field_an_action_names_cannot_be_deleted_or_renamed(strict):
    field = workflow_config.add_field(
        strict.workflow, FieldIn(name="Note", field_type=FieldType.TEXT)
    )
    workflow_config.update_status(
        strict.done,
        StatusPatch(
            actions=actions({"action": "set_field", "params": {"field": "Note", "value": "x"}})
        ),
    )

    with refused(FailureCode.FIELD_IN_USE):
        workflow_config.delete_field(field)
    with refused(FailureCode.FIELD_IN_USE):
        workflow_config.update_field(field, FieldPatch(name="Remark"))


def test_a_status_another_workflow_moves_into_cannot_be_deleted(strict, manager_user):
    default = Workflow.objects.default()
    workflow_config.update_status(
        status_of(default, "resolved"),
        StatusPatch(
            actions=actions(
                {
                    "action": "change_workflow",
                    "params": {"workflow": "Strict", "status": strict.hold.key},
                }
            )
        ),
    )

    with refused(FailureCode.STATUS_IN_USE):
        workflow_config.delete_status(strict.hold, migrate_to=None, actor=manager_user)
    with refused(FailureCode.WORKFLOW_IN_USE):
        workflow_config.update_workflow(
            strict.workflow, WorkflowPatch(name="Renamed"), actor=manager_user
        )


def test_migrate_to_is_checked_even_when_the_status_is_empty(strict, manager_user):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.delete_status(strict.hold, migrate_to=strict.review.id, actor=manager_user)


def test_system_status_orders_stay_one_to_n(strict):
    workflow_config.create_system_status(SystemStatusIn(name="First", color="#000000", order=1))

    orders = list(SystemStatus.objects.order_by("order").values_list("order", flat=True))
    assert orders == list(range(1, len(orders) + 1))


# ── approvals ──


def approval_flow(strict, ticket, celery, approver, mover):
    before_action(
        strict,
        {
            "action": "require_approval",
            "params": {"approvers": approver.username},
            "position": "before",
        },
    )
    put_in(ticket, strict.working)
    lifecycle.move(ticket.id, strict.done.id, actor=mover, force=False, expected_version=None)
    celery.drain()
    return ApprovalRequest.objects.get(run__ticket=ticket)


def test_nobody_approves_their_own_move(ticket, strict, celery, manager_user):
    approval = approval_flow(strict, ticket, celery, manager_user, manager_user)

    with refused(FailureCode.SELF_APPROVAL):
        lifecycle.decide_approval(approval.id, user=manager_user, approve=True, comment="")


def test_an_expired_approval_cannot_be_approved(
    ticket, strict, celery, manager_user, technician_user
):
    approval = approval_flow(strict, ticket, celery, manager_user, technician_user)
    ApprovalRequest.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    with refused(FailureCode.APPROVAL_EXPIRED):
        lifecycle.decide_approval(approval.id, user=manager_user, approve=True, comment="")


def test_a_retried_approval_starts_with_no_old_answer(
    ticket, strict, celery, manager_user, technician_user
):
    approval = approval_flow(strict, ticket, celery, manager_user, technician_user)
    lifecycle.decide_approval(approval.id, user=manager_user, approve=False, comment="not yet")
    celery.drain()

    lifecycle.retry(ticket.id, technician_user)
    celery.drain()

    approval.refresh_from_db()
    assert approval.state == "pending"
    assert approval.comment == ""
    assert approval.decided_by is None


# ── routes ──


def test_reorder_and_validate_are_reachable(api_as, manager_user):
    client = api_as(manager_user)
    ids = [str(i) for i in SystemStatus.objects.values_list("id", flat=True)]

    reorder = client.post(
        f"{BASE}/system-statuses/reorder", json.dumps({"ids": ids}), content_type="application/json"
    )
    validate = client.post(
        f"{BASE}/fields/validate",
        json.dumps({"workflow_id": str(Workflow.objects.default().id), "values": {}}),
        content_type="application/json",
    )

    assert reorder.status_code == 200
    assert validate.status_code == 200
    assert validate.json() == {"valid": True, "violations": []}


def test_the_callback_token_changes_with_each_attempt():
    started = timezone.now()
    run = ActionRun(attempt=1, started_at=started)
    first = callback_token(run)
    run.started_at = started + timedelta(seconds=1)

    assert callback_token(run) != first
