"""
Runbook execution (F12, ADR-0006, ADR-0038). The router sends every RunbookProposal to a person;
`runbooks.execute` and the worker's `runbooks.run` each check the approval again, so a bug
upstream (an item in the wrong queue, a rejection mistaken for an approval, a draft the LLM filled
in wrongly) still cannot reach a live system.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.itsm_mock.models import ExecutionState, ExecutorKind, Runbook, RunbookExecution
from apps.itsm_mock.tests.conftest import (
    approve_catalog,
    mock_runbook,
    record_decision,
    runbook_item,
)
from apps.itsm_mock.utils.executors import RunbookError
from apps.itsm_mock.utils.runbooks import runbooks
from apps.review.models import ReviewAction
from apps.tickets.models import CommentVisibility, TicketComment
from apps.tickets.utils.router import ReviewQueue
from infrastructure.outbound import OutboundNoAnswer, OutboundResponse, OutboundUnavailable

LAN_SUB = "3f9b2c41-0000-4000-8000-00000000a012"
GRANT_VPN = {"target_username": "lan.nt", "group": "/apps/vpn-users"}
RESTART = {"service_name": "vpn-gateway", "host": "vpn01"}


def refused(item, executor, payload, code: str, match: str = "") -> RunbookError:
    with pytest.raises(RunbookError, match=match) as raised:
        runbooks.execute(item.id, executor, payload)
    assert raised.value.code == code
    assert not RunbookExecution.objects.exists()
    return raised.value


def approved_item(people, approver="ha.vt", **kwargs):
    item = runbook_item(people["lan.nt"], **kwargs)
    record_decision(item, people[approver], ReviewAction.APPROVE)
    return item


def audit_actions() -> list[str]:
    return list(
        AuditLog.objects.filter(event__startswith="runbook_")
        .order_by("occurred_at")
        .values_list("event", flat=True)
    )


@pytest.mark.django_db
class TestRefusals:
    def test_runbook_never_runs_without_approval(self, people, iam):
        approve_catalog(people["huy.pq"])
        item = runbook_item(people["lan.nt"])

        refused(item, people["ha.vt"], {"target_username": "lan.nt"}, "not_approved", "NEVER")
        assert iam.calls == []

    def test_a_rejection_is_not_an_approval(self, people):
        approve_catalog(people["huy.pq"])
        item = runbook_item(people["lan.nt"])
        record_decision(item, people["ha.vt"], ReviewAction.REJECT)

        refused(item, people["ha.vt"], {"target_username": "lan.nt"}, "not_approved")

    def test_an_approval_outside_the_runbook_queue(self, people):
        """An approved auto-reply draft is not an approved runbook."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people, queue=ReviewQueue.LOW_CONFIDENCE)

        refused(item, people["ha.vt"], {"target_username": "lan.nt"}, "not_a_runbook_item")

    def test_an_approval_by_an_employee_does_not_count(self, people):
        """FR-PRE1-005: an approval recorded by a non-staff user, e.g. before PRE-1."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people, approver="lan.nt")

        refused(item, people["ha.vt"], {"target_username": "lan.nt"}, "approver_not_staff")

    @pytest.mark.parametrize("role", ["employee", "security"])
    def test_only_a_technician_or_manager_executes(self, people, django_user_model, role):
        approve_catalog(people["huy.pq"])
        item = approved_item(people)
        executor = django_user_model.objects.create_user(username="x", password="x", role=role)

        error = refused(item, executor, {"target_username": "lan.nt"}, "executor_not_staff")
        assert error.status == 403

    def test_a_runbook_the_catalog_does_not_know(self, people):
        item = approved_item(people, runbook_id="RB-DROP-DATABASE")

        refused(item, people["ha.vt"], {"target_username": "lan.nt"}, "unknown_runbook")

    def test_an_unapproved_catalog_runbook_does_not_run(self, people):
        """The seeded runbooks run only once a manager approves them."""
        item = approved_item(people)

        error = refused(
            item, people["ha.vt"], {"target_username": "lan.nt"}, "runbook_not_approved"
        )
        assert error.status == 409

    def test_an_inactive_runbook_does_not_run(self, people):
        approve_catalog(people["huy.pq"])
        Runbook.objects.filter(code="RB-RESET-PASSWORD").update(is_active=False)
        item = approved_item(people)

        refused(item, people["ha.vt"], {"target_username": "lan.nt"}, "unknown_runbook")

    def test_a_payload_missing_required_fields(self, people):
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-GRANT-ACCESS", draft_payload={})

        refused(item, people["duc.tm"], {"target_username": "lan.nt"}, "missing_fields", "group")

    def test_a_group_off_the_runbooks_allow_list(self, people, iam):
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-GRANT-ACCESS")

        refused(
            item,
            people["duc.tm"],
            {"target_username": "lan.nt", "group": "/it/access/lead"},
            "group_not_allowed",
        )
        assert iam.calls == []


@pytest.mark.django_db
def test_reset_targets_only_the_reporter(people, iam):
    """AC-F12-01, BR-F12-02: whatever the proposal says, a reset reaches only the reporter."""
    approve_catalog(people["huy.pq"])
    item = approved_item(people, draft_payload={"target_username": "huy.pq"})

    refused(item, people["ha.vt"], {"target_username": "huy.pq"}, "target_not_reporter")
    assert iam.calls == []


@pytest.mark.django_db
def test_a_reset_sends_the_keycloak_action_email(people, iam, settings):
    """AC-F12-02, BR-F12-05: execute-actions-email UPDATE_PASSWORD for Lan's sub, as the
    runbook client, then a succeeded execution with a comment on the ticket."""
    approve_catalog(people["huy.pq"])
    item = approved_item(people)

    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
    assert execution.state == ExecutionState.QUEUED.value
    runbooks.run(execution.id)

    execution.refresh_from_db()
    assert iam.sent_actions == {LAN_SUB: ["UPDATE_PASSWORD"]}
    assert iam.token_clients == [settings.KEYCLOAK_RUNBOOK_CLIENT_ID]
    assert execution.state == ExecutionState.SUCCEEDED.value
    assert LAN_SUB in execution.external_ref
    assert execution.approved_by == people["ha.vt"]
    assert execution.started_at and execution.finished_at
    comment = TicketComment.objects.get(ticket=item.ticket)
    assert comment.visibility == CommentVisibility.PUBLIC.value
    assert "RB-RESET-PASSWORD" in comment.body_masked
    assert audit_actions() == ["runbook_approved", "runbook_executed"]


@pytest.mark.django_db
def test_unlock_clears_the_brute_force_lock(people, iam):
    approve_catalog(people["huy.pq"])
    item = approved_item(people, runbook_id="RB-UNLOCK-ACCOUNT")

    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
    runbooks.run(execution.id)

    assert iam.changes() == [
        f"DELETE /admin/realms/smart-ticket/attack-detection/brute-force/users/{LAN_SUB}"
    ]
    execution.refresh_from_db()
    assert execution.state == ExecutionState.SUCCEEDED.value


@pytest.mark.django_db
class TestSecondApproval:
    def test_high_risk_needs_second_manager(self, people, iam, api_as):
        """AC-F12-03, BR-F12-03: duc.tm's execute waits; huy.pq's second approval runs it."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people, approver="duc.tm", runbook_id="RB-GRANT-ACCESS")

        response = api_as(people["duc.tm"]).post(
            f"/api/itsm/review-items/{item.id}/execute",
            {"payload": GRANT_VPN},
            content_type="application/json",
        )

        assert response.status_code == 409
        assert response.json()["code"] == "second_approval_required"
        execution_id = response.json()["details"]["execution"]
        assert iam.calls == []

        second = api_as(people["huy.pq"]).post(
            f"/api/itsm/executions/{execution_id}/second-approval"
        )
        assert second.status_code == 200
        assert second.json()["state"] == "queued"
        assert second.json()["second_approver"] == "huy.pq"
        runbooks.run(execution_id)

        assert iam.members == {"/apps/vpn-users": {LAN_SUB}}
        assert RunbookExecution.objects.get().state == ExecutionState.SUCCEEDED.value

    def test_the_first_approver_cannot_give_the_second_approval(self, people, api_as):
        approve_catalog(people["quang.nv"])
        item = approved_item(people, approver="huy.pq", runbook_id="RB-GRANT-ACCESS")
        execution = runbooks.execute(item.id, people["duc.tm"], GRANT_VPN)

        response = api_as(people["huy.pq"]).post(
            f"/api/itsm/executions/{execution.id}/second-approval"
        )

        assert response.status_code == 403
        assert response.json()["code"] == "self_approval"
        execution.refresh_from_db()
        assert execution.state == ExecutionState.AWAITING_SECOND_APPROVAL.value

    def test_the_executor_cannot_give_the_second_approval(self, people):
        approve_catalog(people["quang.nv"])
        item = approved_item(people, runbook_id="RB-GRANT-ACCESS")
        execution = runbooks.execute(item.id, people["huy.pq"], GRANT_VPN)

        with pytest.raises(RunbookError) as raised:
            runbooks.second_approve(execution.id, people["huy.pq"])

        assert raised.value.code == "self_approval"

    def test_a_technician_cannot_give_the_second_approval(self, people, api_as):
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-GRANT-ACCESS")
        execution = runbooks.execute(item.id, people["duc.tm"], GRANT_VPN)

        response = api_as(people["ha.vt"]).post(
            f"/api/itsm/executions/{execution.id}/second-approval"
        )

        assert response.status_code == 403

    def test_the_worker_refuses_a_high_risk_run_without_a_second_approval(self, people, iam):
        """A row queued by any other path is still checked before it runs."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-GRANT-ACCESS")
        execution = runbooks.execute(item.id, people["duc.tm"], GRANT_VPN)
        RunbookExecution.objects.filter(pk=execution.id).update(state="queued")

        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.FAILED.value
        assert "second approval" in execution.error
        assert iam.calls == []


@pytest.mark.django_db
class TestUnknownOutcomes:
    def test_an_n8n_timeout_is_unknown(self, people, n8n, monkeypatch, settings):
        """AC-F12-04, BR-F12-06: n8n accepts, never calls back; 30 s later the outcome is
        unknown, and nothing is sent again."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-RESTART-SERVICE")
        execution = runbooks.execute(item.id, people["ha.vt"], RESTART)
        runbooks.second_approve(execution.id, people["quang.nv"])
        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.RUNNING.value
        assert execution.awaiting_until and execution.started_at
        waited = execution.awaiting_until - execution.started_at
        assert waited.total_seconds() == pytest.approx(settings.ITSM_EXECUTOR_TIMEOUT_SEC, abs=1)

        later = timezone.now() + timedelta(seconds=settings.ITSM_EXECUTOR_TIMEOUT_SEC + 1)
        monkeypatch.setattr(timezone, "now", lambda: later)
        assert runbooks.sweep() == 1
        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.UNKNOWN.value
        assert len(n8n.sent) == 1
        assert audit_actions()[-1] == "runbook_unknown"
        note = TicketComment.objects.get(ticket=item.ticket)
        assert note.visibility == CommentVisibility.INTERNAL.value

    def test_timeout_after_send_is_unknown_not_retried(self, people, iam):
        """BR-F12-06: Keycloak received the change and never answered."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people)
        iam.change_hangs = True
        execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})

        runbooks.run(execution.id)
        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.UNKNOWN.value
        assert len(iam.changes()) == 1
        with pytest.raises(RunbookError) as raised:
            runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
        assert raised.value.code == "execution_exists"

    def test_n8n_without_an_answer_is_unknown(self, people, n8n):
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-RESTART-SERVICE")
        n8n.answer = OutboundNoAnswer("read timeout")
        execution = runbooks.execute(item.id, people["ha.vt"], RESTART)
        runbooks.second_approve(execution.id, people["huy.pq"])

        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.UNKNOWN.value

    def test_an_unreachable_n8n_is_failed_and_may_be_executed_again(self, people, n8n):
        """Nothing was sent, so the outcome is known; a person may try again."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-RESTART-SERVICE")
        n8n.answer = OutboundUnavailable("connection refused")
        first = runbooks.execute(item.id, people["ha.vt"], RESTART)
        runbooks.second_approve(first.id, people["huy.pq"])
        runbooks.run(first.id)

        again = runbooks.execute(item.id, people["ha.vt"], RESTART)

        first.refresh_from_db()
        assert first.state == ExecutionState.FAILED.value
        assert again.attempt == 2
        assert again.idempotency_key == f"{item.id}:2"

    def test_an_unreachable_keycloak_is_failed(self, people, iam):
        approve_catalog(people["huy.pq"])
        item = approved_item(people)
        iam.down = True
        execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})

        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.FAILED.value
        assert audit_actions()[-1] == "runbook_failed"

    def test_a_keycloak_server_error_on_the_change_is_unknown(self, people, iam):
        approve_catalog(people["huy.pq"])
        item = approved_item(people)
        iam.change_status = 500
        execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})

        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.UNKNOWN.value

    def test_a_worker_lost_mid_call_leaves_an_unknown(self, people, iam, monkeypatch, settings):
        approve_catalog(people["huy.pq"])
        item = approved_item(people)
        execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
        runbooks.start(execution.id)

        later = timezone.now() + timedelta(seconds=settings.ITSM_RUN_STUCK_SEC + 1)
        monkeypatch.setattr(timezone, "now", lambda: later)
        runbooks.sweep()
        runbooks.run(execution.id)

        execution.refresh_from_db()
        assert execution.state == ExecutionState.UNKNOWN.value
        assert iam.calls == []

    def test_a_person_resolves_an_unknown(self, people, iam, api_as):
        """UC-F12-02, FR-F12-007."""
        approve_catalog(people["huy.pq"])
        item = approved_item(people)
        iam.change_hangs = True
        execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
        runbooks.run(execution.id)
        client = api_as(people["duc.tm"])
        url = f"/api/itsm/executions/{execution.id}/resolve"

        blank = client.post(
            url, {"state": "succeeded", "note": "  "}, content_type="application/json"
        )
        done = client.post(
            url,
            {"state": "succeeded", "note": "Lan got the email"},
            content_type="application/json",
        )
        again = client.post(
            url, {"state": "failed", "note": "second try"}, content_type="application/json"
        )

        assert blank.status_code == 422
        assert done.status_code == 200
        assert done.json()["state"] == "succeeded"
        assert done.json()["resolved_by"] == "duc.tm"
        assert again.status_code == 409
        assert again.json()["code"] == "not_unknown"
        assert audit_actions()[-1] == "runbook_resolved"


@pytest.mark.django_db
def test_what_runs_is_what_the_approver_saw(people, iam):
    """AC-F12-05, BR-F12-04: the approver's edit is stored and is what reaches Keycloak."""
    approve_catalog(people["huy.pq"])
    item = approved_item(people, draft_payload={"target_username": "huy.pq"})

    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
    runbooks.run(execution.id)

    execution.refresh_from_db()
    assert execution.executed_payload == {"target_username": "lan.nt"}
    assert execution.payload == {"target_username": "huy.pq"}
    assert list(iam.sent_actions) == [LAN_SUB]


@pytest.mark.django_db
def test_mock_executor_matches_old_behaviour(people):
    """The pre-F12 simulated result, now from the mock executor."""
    mock_runbook("RB-MOCK", people["huy.pq"])
    item = approved_item(people, runbook_id="RB-MOCK")

    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
    runbooks.run(execution.id)

    execution.refresh_from_db()
    assert execution.state == ExecutionState.SUCCEEDED.value
    assert execution.result == {
        "simulated": True,
        "runbook": "A mock runbook",
        "applied_payload": {"target_username": "lan.nt"},
    }
    assert execution.executed_by == people["ha.vt"]
    assert execution.status is None


@pytest.mark.django_db
def test_a_row_past_queued_is_never_sent_again(people, monkeypatch):
    from apps.itsm_mock.utils.executors import EXECUTORS, MockExecutor

    mock_runbook("RB-MOCK", people["huy.pq"])
    item = approved_item(people, runbook_id="RB-MOCK")
    runs = []

    def counted(execution):
        runs.append(execution.id)
        return MockExecutor().run(execution)

    monkeypatch.setattr(EXECUTORS[ExecutorKind.MOCK], "run", counted)
    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})

    runbooks.run(execution.id)
    runbooks.run(execution.id)

    assert runs == [execution.id]


@pytest.mark.django_db
def test_an_executor_crash_is_unknown_not_retried(people, monkeypatch):
    from apps.itsm_mock.utils.executors import EXECUTORS

    mock_runbook("RB-MOCK", people["huy.pq"])
    item = approved_item(people, runbook_id="RB-MOCK")
    monkeypatch.setattr(EXECUTORS[ExecutorKind.MOCK], "run", lambda e: 1 / 0)
    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})

    runbooks.run(execution.id)

    execution.refresh_from_db()
    assert execution.state == ExecutionState.UNKNOWN.value
    assert "ZeroDivisionError" in execution.error


@pytest.mark.django_db
def test_the_worker_refuses_a_run_whose_approval_disappeared(people):
    """ADR-0006 checked again at run time."""
    mock_runbook("RB-MOCK", people["huy.pq"])
    item = approved_item(people, runbook_id="RB-MOCK")
    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
    item.decisions.all().delete()

    runbooks.run(execution.id)

    execution.refresh_from_db()
    assert execution.state == ExecutionState.FAILED.value
    assert "ADR-0006" in execution.error


@pytest.mark.django_db
def test_a_catalog_change_after_approval_stops_the_run(people):
    mock_runbook("RB-MOCK", people["huy.pq"])
    item = approved_item(people, runbook_id="RB-MOCK")
    execution = runbooks.execute(item.id, people["ha.vt"], {"target_username": "lan.nt"})
    Runbook.objects.filter(code="RB-MOCK").update(approved_at=timezone.now() + timedelta(seconds=1))

    runbooks.run(execution.id)

    execution.refresh_from_db()
    assert execution.state == ExecutionState.FAILED.value
    assert "changed after" in execution.error


@pytest.mark.django_db
class TestCallback:
    def started(self, people, n8n):
        approve_catalog(people["huy.pq"])
        item = approved_item(people, runbook_id="RB-RESTART-SERVICE")
        execution = runbooks.execute(item.id, people["ha.vt"], RESTART)
        runbooks.second_approve(execution.id, people["huy.pq"])
        runbooks.run(execution.id)
        return RunbookExecution.objects.get(pk=execution.id)

    def test_n8n_gets_the_signed_callback(self, people, n8n):
        execution = self.started(people, n8n)

        body = n8n.sent[0]["body"]
        assert n8n.sent[0]["url"] == "https://n8n.congty.vn/webhook/restart-service"
        assert body["callbackUrl"].endswith(f"/api/itsm/executions/{execution.id}/callback")
        assert body["callbackToken"] == execution.callback_token()
        assert body["payload"] == RESTART

    def test_the_callback_finishes_the_run_once(self, people, n8n, client):
        execution = self.started(people, n8n)
        url = f"/api/itsm/executions/{execution.id}/callback"
        body = {"state": "succeeded", "external_ref": "n8n-run-42"}
        headers = {"X-Itsm-Token": execution.callback_token()}

        first = client.post(url, body, content_type="application/json", headers=headers)
        second = client.post(url, body, content_type="application/json", headers=headers)

        assert first.status_code == 204
        assert second.status_code == 409
        execution.refresh_from_db()
        assert execution.state == ExecutionState.SUCCEEDED.value
        assert execution.external_ref == "n8n-run-42"

    def test_a_bad_callback_token_is_refused(self, people, n8n, client):
        execution = self.started(people, n8n)

        response = client.post(
            f"/api/itsm/executions/{execution.id}/callback",
            {"state": "succeeded"},
            content_type="application/json",
            headers={"X-Itsm-Token": "forged"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "bad_callback_token"
        execution.refresh_from_db()
        assert execution.state == ExecutionState.RUNNING.value

    def test_a_non_2xx_from_n8n_is_failed(self, people, n8n):
        n8n.answer = OutboundResponse(404, "no such webhook")
        execution = self.started(people, n8n)

        assert execution.state == ExecutionState.FAILED.value
        assert "404" in execution.error
