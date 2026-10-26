"""The lifecycle engine: pipeline moves nothing can refuse, governed moves, and the actions they run."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Message
from apps.lifecycle.models import ActionRun, ApprovalRequest, Transfer, Workflow
from apps.lifecycle.request_schema import FieldIn, RuleIn, StatusPatch, TransitionPatch
from apps.lifecycle.tests.conftest import actions, make_ticket, put_in, status_of
from apps.lifecycle.utils.actions import callback_token
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.fields import field_values
from apps.lifecycle.utils.rules import FieldType, RuleCode
from apps.lifecycle.utils.vocabulary import (
    FailureCode,
    PipelineStatus,
    RunState,
    TransferState,
    Trigger,
)
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def default_status(key: str):
    return status_of(Workflow.objects.default(), key)


def reload(ticket: Ticket) -> Ticket:
    return Ticket.objects.select_related("workflow_status").get(pk=ticket.pk)


def last_transfer(ticket: Ticket) -> Transfer:
    return ticket.transfers.latest("created_at")


# ── the pipeline's moves ──


def test_a_submitted_ticket_starts_at_new_in_the_default_workflow(employee_user):
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)

    ticket = reload(ticket)
    assert ticket.status == "new"
    assert ticket.workflow_status == default_status("new")
    transfer = last_transfer(ticket)
    assert transfer.trigger == Trigger.CREATE.value
    assert transfer.before_status is None
    assert transfer.state == TransferState.COMPLETED.value


def test_a_pipeline_move_is_recorded_and_audited(ticket):
    lifecycle.system_move(ticket, PipelineStatus.ESCALATED)

    assert reload(ticket).status == "escalated"
    assert last_transfer(ticket).trigger == Trigger.SYSTEM.value
    assert AuditLog.objects.filter(ticket_id=ticket.id, event="ticket_status_changed").exists()


def test_a_pipeline_move_updates_the_callers_instance(ticket):
    lifecycle.system_move(ticket, PipelineStatus.AUTO_REPLIED)

    assert ticket.status == "auto_replied"
    assert ticket.resolved_at is not None


def test_a_pipeline_move_cancels_a_move_in_flight(ticket, strict, celery, webhooks):
    put_in(ticket, strict.working)
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "call_webhook",
                    "params": {"url": "http://localhost/x"},
                    "position": "before",
                }
            )
        ),
    )
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    assert reload(ticket).waiting_transform

    lifecycle.system_move(ticket, PipelineStatus.REOPENED)
    celery.drain()

    ticket = reload(ticket)
    assert ticket.status == "reopened"
    assert not ticket.waiting_transform
    cancelled = ticket.transfers.get(after_status=strict.done)
    assert cancelled.state == TransferState.CANCELLED.value
    assert cancelled.failure_code == FailureCode.SUPERSEDED_BY_PIPELINE.value
    assert webhooks.calls == []


def test_a_pipeline_status_missing_from_a_workflow_is_recreated(ticket, strict):
    put_in(ticket, strict.working)
    strict.workflow.statuses.filter(key="reopened").delete()

    lifecycle.system_move(ticket, PipelineStatus.REOPENED)

    moved = reload(ticket)
    assert moved.workflow_status is not None
    assert moved.workflow_status.workflow == strict.workflow
    assert moved.status == "reopened"


def test_entering_a_completed_stage_sets_resolved_at_and_leaving_clears_it(ticket, manager_user):
    lifecycle.system_move(ticket, PipelineStatus.AUTO_REPLIED)
    assert reload(ticket).resolved_at is not None

    lifecycle.move(
        ticket.id,
        default_status("in_progress").id,
        actor=manager_user,
        force=False,
        expected_version=None,
    )

    assert reload(ticket).resolved_at is None


# ── people's moves ──


def test_a_move_in_an_open_workflow_commits_at_once(ticket, technician_user):
    version = reload(ticket).version

    lifecycle.move(
        ticket.id,
        default_status("in_progress").id,
        actor=technician_user,
        force=False,
        expected_version=version,
    )

    ticket = reload(ticket)
    assert ticket.status == "in_progress"
    assert ticket.version == version + 1
    assert not ticket.waiting_transform
    assert last_transfer(ticket).state == TransferState.COMPLETED.value
    assert last_transfer(ticket).actor == technician_user


def test_a_strict_workflow_refuses_an_unmodelled_move(ticket, strict, technician_user):
    put_in(ticket, strict.review)

    with pytest.raises(LifecycleError) as e:
        lifecycle.move(
            ticket.id, strict.done.id, actor=technician_user, force=False, expected_version=None
        )

    assert e.value.code is FailureCode.TRANSITION_NOT_ALLOWED
    assert reload(ticket).status == "pending_review"
    assert not ticket.transfers.filter(after_status=strict.done).exists()


def test_a_stale_version_is_refused(ticket, technician_user):
    with pytest.raises(LifecycleError) as e:
        lifecycle.move(
            ticket.id,
            default_status("in_progress").id,
            actor=technician_user,
            force=False,
            expected_version=reload(ticket).version - 1,
        )

    assert e.value.code is FailureCode.VERSION_CONFLICT


def test_a_ticket_in_triage_cannot_be_moved_by_a_person(employee_user, manager_user):
    ticket = make_ticket(employee_user, at=PipelineStatus.AWAITING_REQUESTER)

    with pytest.raises(LifecycleError) as e:
        lifecycle.move(
            ticket.id,
            default_status("in_progress").id,
            actor=manager_user,
            force=True,
            expected_version=None,
        )

    assert e.value.code is FailureCode.TICKET_IN_TRIAGE
    assert reload(ticket).status == "awaiting_requester"


def test_a_person_cannot_move_a_ticket_into_a_pipeline_status(ticket, manager_user):
    lifecycle.move(
        ticket.id,
        default_status("in_progress").id,
        actor=manager_user,
        force=False,
        expected_version=None,
    )

    with pytest.raises(LifecycleError) as e:
        lifecycle.move(
            ticket.id,
            default_status("auto_replied").id,
            actor=manager_user,
            force=True,
            expected_version=None,
        )

    assert e.value.code is FailureCode.PIPELINE_STATUS_TARGET
    assert reload(ticket).status == "in_progress"


def test_a_second_move_while_the_first_is_running_is_refused(ticket, strict, celery, webhooks):
    put_in(ticket, strict.review)
    workflow_config.update_status(
        strict.working,
        StatusPatch(actions=actions({"action": "assign_team", "params": {"team": "network"}})),
    )
    lifecycle.request_move(ticket.id, strict.working.id, actor=None, trigger=Trigger.MANUAL)

    with pytest.raises(LifecycleError) as e:
        lifecycle.request_move(ticket.id, strict.hold.id, actor=None, trigger=Trigger.MANUAL)

    assert e.value.code is FailureCode.TICKET_TRANSFORMING
    assert e.value.status == 409


def resolution_gate(strict, manager_user):
    field = workflow_config.add_field(
        strict.workflow, FieldIn(name="Resolution", field_type=FieldType.TEXTAREA)
    )
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            rules=[
                RuleIn(field_id=field.id, rule=RuleCode.REQUIRED),
                RuleIn(field_id=field.id, rule=RuleCode.MIN_LENGTH, params={"min": 10}),
            ]
        ),
    )
    return field


def test_a_transition_rule_refuses_the_move_and_names_every_broken_rule(
    ticket, strict, manager_user, technician_user
):
    resolution_gate(strict, manager_user)
    put_in(ticket, strict.working)

    with pytest.raises(LifecycleError) as e:
        lifecycle.move(
            ticket.id, strict.done.id, actor=technician_user, force=False, expected_version=None
        )

    assert e.value.code is FailureCode.RULE_VIOLATION
    assert [d["rule"] for d in e.value.details] == ["required"]
    assert reload(ticket).status == strict.working.key


def test_a_move_passes_once_the_field_satisfies_the_rules(
    ticket, strict, manager_user, technician_user
):
    resolution_gate(strict, manager_user)
    put_in(ticket, strict.working)
    field_values.write_by_name(ticket, {"Resolution": "Replaced the VPN client"}, depth=0)

    lifecycle.move(
        ticket.id, strict.done.id, actor=technician_user, force=False, expected_version=None
    )

    assert reload(ticket).status == strict.done.key


def test_force_skips_rules_but_not_actions(ticket, strict, manager_user, celery):
    resolution_gate(strict, manager_user)
    workflow_config.update_status(
        strict.done,
        StatusPatch(actions=actions({"action": "assign_team", "params": {"team": "hardware"}})),
    )
    put_in(ticket, strict.working)

    lifecycle.move(ticket.id, strict.done.id, actor=manager_user, force=True, expected_version=None)
    celery.drain()

    ticket = reload(ticket)
    assert ticket.status == strict.done.key
    assert ticket.assigned_team == "hardware"
    assert last_transfer(ticket).trigger == Trigger.FORCE.value


# ── actions ──


def webhook_before(strict, *, url="http://localhost/check"):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {"action": "call_webhook", "params": {"url": url}, "position": "before"}
            )
        ),
    )


def test_a_move_waits_for_its_before_actions_then_commits(ticket, strict, celery, webhooks):
    webhook_before(strict)
    put_in(ticket, strict.working)

    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    assert reload(ticket).status == strict.working.key
    assert reload(ticket).waiting_transform

    celery.drain()

    ticket = reload(ticket)
    assert ticket.status == strict.done.key
    assert not ticket.waiting_transform
    assert last_transfer(ticket).state == TransferState.COMPLETED.value
    assert len(webhooks.calls) == 1


def test_a_before_action_that_refuses_keeps_the_ticket_where_it_was(
    ticket, strict, celery, webhooks
):
    webhook_before(strict)
    webhooks.status = 409
    webhooks.text = "change freeze"
    put_in(ticket, strict.working)

    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()

    ticket = reload(ticket)
    assert ticket.status == strict.working.key
    assert not ticket.waiting_transform
    transfer = last_transfer(ticket)
    assert transfer.state == TransferState.FAILED.value
    assert transfer.failure_code == FailureCode.ACTION_ABORTED.value
    assert "change freeze" in transfer.failure_reason


def test_a_transient_failure_is_retried_with_backoff_then_fails(ticket, strict, celery, webhooks):
    webhook_before(strict)
    webhooks.status = 503
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)

    countdowns: list[float | None] = []
    while celery.sent and len(countdowns) < 10:
        countdowns.append(celery.step())

    run = ActionRun.objects.get(transfer=last_transfer(ticket))
    assert run.attempt == 3
    assert run.state == RunState.FAILED.value
    assert countdowns == [None, 4.0, 8.0]
    assert reload(ticket).status == strict.working.key
    assert last_transfer(ticket).failure_code == FailureCode.ACTION_FAILED.value


def test_an_after_failure_keeps_the_move_and_retry_reruns_only_what_failed(
    ticket, strict, celery, webhooks, technician_user
):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "call_webhook",
                    "params": {"url": "http://localhost/ok"},
                    "position": "after",
                },
                {
                    "action": "assign_user",
                    "params": {"username": technician_user.username},
                    "position": "after",
                },
            )
        ),
    )
    put_in(ticket, strict.working)
    technician_user.is_active = False
    technician_user.save()

    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()

    ticket = reload(ticket)
    assert ticket.status == strict.done.key
    transfer = last_transfer(ticket)
    assert transfer.state == TransferState.FAILED.value
    assert transfer.failure_code == FailureCode.INVALID_PARAM.value
    assert len(webhooks.calls) == 1

    technician_user.is_active = True
    technician_user.save()
    lifecycle.retry(ticket.id, technician_user)
    celery.drain()

    assert last_transfer(ticket).state == TransferState.COMPLETED.value
    assert reload(ticket).assigned_to == technician_user
    assert len(webhooks.calls) == 1


def test_retry_with_nothing_failed_is_refused(ticket, technician_user):
    with pytest.raises(LifecycleError) as e:
        lifecycle.retry(ticket.id, technician_user)

    assert e.value.code is FailureCode.NOTHING_TO_RETRY


def test_retry_refuses_a_transfer_the_ticket_has_moved_past(
    ticket, strict, celery, webhooks, technician_user
):
    webhook_before(strict)
    webhooks.status = 400
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()
    lifecycle.request_move(ticket.id, strict.hold.id, actor=None, trigger=Trigger.MANUAL)
    lifecycle.request_move(ticket.id, strict.working.id, actor=None, trigger=Trigger.MANUAL)
    lifecycle.request_move(ticket.id, strict.hold.id, actor=None, trigger=Trigger.MANUAL)

    with pytest.raises(LifecycleError) as e:
        lifecycle.retry(ticket.id, technician_user)

    assert e.value.code is FailureCode.NOTHING_TO_RETRY


def test_a_status_move_inside_a_transfer_waits_for_it_then_follows(ticket, manager_user, celery):
    workflow_config.update_status(
        default_status("resolved"),
        StatusPatch(actions=actions({"action": "move_status", "params": {"status": "closed"}})),
    )

    lifecycle.move(
        ticket.id,
        default_status("resolved").id,
        actor=manager_user,
        force=False,
        expected_version=None,
    )
    celery.drain()

    ticket = reload(ticket)
    assert ticket.status == "closed"
    follow = last_transfer(ticket)
    assert follow.trigger == Trigger.ACTION.value
    assert follow.depth == 1
    assert follow.parent is not None and follow.parent.after_status is not None
    assert follow.parent.after_status.key == "resolved"


def test_an_automation_loop_stops_at_the_chain_depth(ticket, manager_user, celery, settings):
    workflow_config.update_status(
        default_status("in_progress"),
        StatusPatch(actions=actions({"action": "move_status", "params": {"status": "on_hold"}})),
    )
    workflow_config.update_status(
        default_status("on_hold"),
        StatusPatch(
            actions=actions({"action": "move_status", "params": {"status": "in_progress"}})
        ),
    )

    lifecycle.move(
        ticket.id,
        default_status("in_progress").id,
        actor=manager_user,
        force=False,
        expected_version=None,
    )
    celery.drain()

    depth = settings.THRESHOLDS.lifecycle.max_chain_depth
    transfers = list(ticket.transfers.exclude(trigger__in=["create", "system"]))
    assert len(transfers) == depth + 1
    last = last_transfer(ticket)
    assert last.state == TransferState.FAILED.value
    assert last.failure_code == FailureCode.AUTOMATION_DEPTH_EXCEEDED.value
    assert not reload(ticket).waiting_transform


def approval_before(strict, approvers: str):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "require_approval",
                    "params": {"approvers": approvers, "message": "Close it?"},
                    "position": "before",
                }
            )
        ),
    )


def test_an_approval_holds_the_move_until_an_approver_approves(
    ticket, strict, celery, manager_user, technician_user
):
    approval_before(strict, manager_user.username)
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=technician_user, trigger=Trigger.MANUAL)
    celery.drain()
    approval = ApprovalRequest.objects.get(run__transfer=last_transfer(ticket))
    assert reload(ticket).status == strict.working.key
    assert Message.objects.filter(
        user=manager_user, event="approval.requested", channel="in_app"
    ).exists()

    with pytest.raises(LifecycleError) as e:
        lifecycle.decide_approval(approval.id, user=technician_user, approve=True, comment="")
    assert e.value.code is FailureCode.NOT_AN_APPROVER

    lifecycle.decide_approval(approval.id, user=manager_user, approve=True, comment="ok")
    celery.drain()

    assert reload(ticket).status == strict.done.key
    assert last_transfer(ticket).state == TransferState.COMPLETED.value


def test_the_approver_is_told(ticket, strict, celery, technician_user, django_user_model):
    """AC-F4-06: an in-app notice for the approver, linking to the approval (closes TODO 14.3)."""
    huy = django_user_model.objects.create_user(username="huy.pq", password="x", role="manager")
    approval_before(strict, "huy.pq")
    put_in(ticket, strict.working)

    lifecycle.request_move(ticket.id, strict.done.id, actor=technician_user, trigger=Trigger.MANUAL)
    celery.drain()

    approval = ApprovalRequest.objects.get(run__transfer=last_transfer(ticket))
    (notice,) = Message.objects.filter(user=huy, event="approval.requested", channel="in_app")
    assert notice.link == f"/tickets/{ticket.public_id}?approval={approval.id}"
    assert notice.event_id == approval.id
    assert technician_user.username in notice.body
    assert "Close it?" in notice.body


def test_a_rejection_stops_the_move_with_the_approvers_name(ticket, strict, celery, manager_user):
    approval_before(strict, manager_user.username)
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()
    approval = ApprovalRequest.objects.get(run__transfer=last_transfer(ticket))

    lifecycle.decide_approval(approval.id, user=manager_user, approve=False, comment="not yet")
    celery.drain()

    transfer = last_transfer(ticket)
    assert transfer.state == TransferState.FAILED.value
    assert transfer.failure_code == FailureCode.APPROVAL_REJECTED.value
    assert transfer.failure_reason == f"Rejected by {manager_user.username}: not yet"
    assert reload(ticket).status == strict.working.key


def n8n_before(strict):
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(
            actions=actions(
                {
                    "action": "trigger_n8n",
                    "params": {"webhook_url": "http://localhost/n8n", "payload": '{"a": 1}'},
                    "position": "before",
                }
            )
        ),
    )


def test_an_n8n_run_waits_for_a_callback_with_its_token(ticket, strict, celery, webhooks):
    n8n_before(strict)
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()
    run = ActionRun.objects.get(transfer=last_transfer(ticket))
    sent = webhooks.calls[0]["body"]
    assert sent["callbackToken"] == callback_token(run)
    assert sent["payload"] == {"a": 1}
    assert run.state == RunState.RUNNING.value

    with pytest.raises(LifecycleError) as e:
        lifecycle.complete_callback(run.id, token="forged", success=True, message="", output=None)
    assert e.value.code is FailureCode.BAD_CALLBACK_TOKEN

    lifecycle.complete_callback(
        run.id, token=sent["callbackToken"], success=True, message="done", output={"x": 1}
    )
    celery.drain()

    assert reload(ticket).status == strict.done.key


def test_the_watchdog_fails_a_callback_that_never_came(ticket, strict, celery, webhooks):
    n8n_before(strict)
    put_in(ticket, strict.working)
    lifecycle.request_move(ticket.id, strict.done.id, actor=None, trigger=Trigger.MANUAL)
    celery.drain()
    ActionRun.objects.filter(transfer=last_transfer(ticket)).update(
        awaiting_until=timezone.now() - timedelta(seconds=1)
    )

    counts = lifecycle.sweep()
    celery.drain()

    assert counts["runs_timed_out"] == 1
    transfer = last_transfer(ticket)
    assert transfer.state == TransferState.FAILED.value
    assert transfer.failure_code == FailureCode.CALLBACK_TIMEOUT.value
    assert reload(ticket).status == strict.working.key
    assert not reload(ticket).waiting_transform


def test_the_watchdog_unlocks_a_ticket_left_waiting_with_nothing_in_flight(ticket):
    Ticket.objects.filter(pk=ticket.pk).update(waiting_transform=True)

    assert lifecycle.sweep()["unlocked"] == 1
    assert not reload(ticket).waiting_transform


# ── changing workflow ──


def test_changing_workflow_carries_fields_of_the_same_name_and_type(ticket, strict, manager_user):
    default = Workflow.objects.default()
    workflow_config.add_field(default, FieldIn(name="Resolution", field_type=FieldType.TEXTAREA))
    workflow_config.add_field(default, FieldIn(name="Vendor", field_type=FieldType.TEXT))
    workflow_config.add_field(
        strict.workflow, FieldIn(name="Resolution", field_type=FieldType.TEXTAREA)
    )
    field_values.write_by_name(ticket, {"Resolution": "Reinstalled", "Vendor": "Acme"}, depth=0)

    lifecycle.change_workflow(ticket.id, strict.working.id, actor=manager_user)

    assert reload(ticket).workflow_status == strict.working
    assert field_values.by_name(ticket) == {"Resolution": "Reinstalled"}
    audit = AuditLog.objects.filter(ticket_id=ticket.id, event="ticket_status_changed").latest(
        "occurred_at"
    )
    assert audit.payload["dropped_fields"] == ["Vendor"]


def test_adopting_tickets_needs_every_custom_status_mapped(ticket, strict, manager_user):
    lifecycle.move(
        ticket.id,
        default_status("in_progress").id,
        actor=manager_user,
        force=False,
        expected_version=None,
    )

    with pytest.raises(LifecycleError) as e:
        lifecycle.adopt_tickets(Workflow.objects.default(), strict.workflow, {}, actor=manager_user)
    assert e.value.code is FailureCode.UNMAPPED_STATUSES
    assert {d["key"] for d in e.value.details} >= {
        "in_progress",
        "on_hold",
        "waiting_on_requester",
        "resolved",
        "closed",
    }

    default = Workflow.objects.default()
    mapping = {
        status_of(default, k).id: strict.working.id
        for k in ("in_progress", "on_hold", "waiting_on_requester", "resolved", "closed")
    }
    result = lifecycle.adopt_tickets(default, strict.workflow, mapping, actor=manager_user)

    assert result.moved >= 1
    assert reload(ticket).workflow_status == strict.working


def test_a_pipeline_status_is_adopted_into_the_same_pipeline_status(ticket, strict, manager_user):
    default = Workflow.objects.default()
    mapping = {
        status_of(default, k).id: strict.working.id
        for k in ("in_progress", "on_hold", "waiting_on_requester", "resolved", "closed")
    }

    lifecycle.adopt_tickets(default, strict.workflow, mapping, actor=manager_user)

    assert reload(ticket).workflow_status == strict.review
