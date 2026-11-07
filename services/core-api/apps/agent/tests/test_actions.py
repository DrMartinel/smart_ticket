"""Applying what an agent left: a confirm runs only as proposed, a draft is a person's decision
(BR-F15-06, BR-F15-07, ADR-0006)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.testing import api_client_for
from apps.agent.models import AgentAction, AgentActionState
from apps.agent.tests.test_tiers import as_agent, runbook_item
from apps.agent.utils.actions import AgentCall
from apps.audit.context import audit_context
from apps.audit.models import AuditLog
from apps.itsm_mock.utils.executors import RunbookError
from apps.itsm_mock.utils.runbooks import runbooks
from apps.review.models import DecidedVia, ReviewAction, ReviewDecision

pytestmark = pytest.mark.django_db


def proposed_claim(technician, item) -> AgentAction:
    response = as_agent(technician, "claim_review_item").post(f"/api/review/items/{item.id}/claim")
    assert response.status_code == 202
    return AgentAction.objects.get(id=response.json()["action_id"])


def apply(client, path: str, action: AgentAction, body: dict | None = None):
    headers = {"HTTP_X_AGENT_ACTION": str(action.id)}
    if body is None:
        return client.post(path, **headers)
    return client.post(path, body, content_type="application/json", **headers)


def test_a_confirmed_call_runs_as_the_user_and_is_audited_via_the_agent(
    technician_user, employee_user
):
    item = runbook_item(employee_user)
    action = proposed_claim(technician_user, item)

    response = apply(api_client_for(technician_user), f"/api/review/items/{item.id}/claim", action)

    assert response.status_code == 200
    item.refresh_from_db()
    assert item.state == "claimed"
    assert item.claimed_by == technician_user
    action.refresh_from_db()
    assert action.state == AgentActionState.APPLIED.value
    assert action.resolved_by == technician_user
    row = AuditLog.objects.get(event="agent_action_applied")
    assert row.actor_id == technician_user.id
    assert row.payload["via"] == "agent"
    assert row.payload["agent_action_id"] == str(action.id)
    assert row.payload["confirmed_by"] == str(technician_user.id)


def test_a_confirm_applied_to_another_target_is_refused(technician_user, employee_user):
    item, other = runbook_item(employee_user), runbook_item(employee_user)
    action = proposed_claim(technician_user, item)

    response = apply(api_client_for(technician_user), f"/api/review/items/{other.id}/claim", action)

    assert response.status_code == 409
    assert response.json()["code"] == "agent_action_mismatch"
    other.refresh_from_db()
    assert other.state == "pending"
    action.refresh_from_db()
    assert action.state == AgentActionState.PENDING.value


def test_a_confirm_hash_covers_the_body():
    request = RequestFactory().post("/api/tickets/TKT-1/comments")
    proposed = AgentCall.of(request, {"public_id": "TKT-1", "body": "Đã khởi động lại máy"})
    same = AgentCall.of(request, {"public_id": "TKT-1", "body": "Đã khởi động lại máy"})
    edited = AgentCall.of(request, {"public_id": "TKT-1", "body": "Đã khởi động lại máy, vẫn lỗi"})

    assert proposed.sha256() == same.sha256()
    assert proposed.sha256() != edited.sha256()


def test_an_agent_cannot_apply_an_action(technician_user, employee_user):
    item = runbook_item(employee_user)
    action = proposed_claim(technician_user, item)

    response = apply(
        as_agent(technician_user, "claim_review_item"), f"/api/review/items/{item.id}/claim", action
    )

    assert response.status_code == 202
    assert response.json()["action_id"] != str(action.id)
    item.refresh_from_db()
    assert item.state == "pending"
    action.refresh_from_db()
    assert action.state == AgentActionState.PENDING.value


def test_an_expired_action_is_refused_and_marked(technician_user, employee_user):
    item = runbook_item(employee_user)
    action = proposed_claim(technician_user, item)
    AgentAction.objects.filter(id=action.id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    response = apply(api_client_for(technician_user), f"/api/review/items/{item.id}/claim", action)

    assert response.status_code == 410
    assert response.json()["code"] == "agent_action_expired"
    action.refresh_from_db()
    assert action.state == AgentActionState.EXPIRED.value


def test_someone_elses_action_is_not_theirs_to_apply(technician_user, employee_user, manager_user):
    item = runbook_item(employee_user)
    action = proposed_claim(technician_user, item)

    response = apply(api_client_for(manager_user), f"/api/review/items/{item.id}/claim", action)

    assert response.status_code == 409
    assert response.json()["code"] == "agent_action_not_pending"
    item.refresh_from_db()
    assert item.state == "pending"


def test_a_failed_apply_leaves_the_action_pending(technician_user, employee_user, manager_user):
    item = runbook_item(employee_user)
    action = proposed_claim(technician_user, item)
    api_client_for(manager_user).post(f"/api/review/items/{item.id}/claim")

    response = apply(api_client_for(technician_user), f"/api/review/items/{item.id}/claim", action)

    assert response.status_code == 409
    action.refresh_from_db()
    assert action.state == AgentActionState.PENDING.value


def test_an_applied_draft_is_the_persons_decision(technician_user, employee_user):
    item = runbook_item(employee_user)
    drafted = as_agent(technician_user).post(
        f"/api/review/items/{item.id}/decide",
        {"action_taken": "approve", "time_spent_sec": 0},
        content_type="application/json",
    )
    draft = AgentAction.objects.get(id=drafted.json()["details"]["draft_id"])

    response = apply(
        api_client_for(technician_user),
        f"/api/review/items/{item.id}/decide",
        draft,
        {"action_taken": "reject", "override_reason": "not for VPN admins", "time_spent_sec": 40},
    )

    assert response.status_code == 200
    decision = ReviewDecision.objects.get(review_item=item)
    assert decision.reviewer == technician_user
    assert decision.action_taken == "reject"
    assert decision.decided_via == DecidedVia.HUMAN.value
    assert decision.from_agent_action_id == draft.id
    draft.refresh_from_db()
    assert draft.state == AgentActionState.APPLIED.value
    row = AuditLog.objects.get(event="agent_action_applied")
    assert row.actor_id == technician_user.id
    assert row.payload["agent_draft_id"] == str(draft.id)
    assert "via" not in row.payload


def test_a_decision_cannot_be_stored_as_made_by_anyone_but_a_person(technician_user, employee_user):
    item = runbook_item(employee_user)

    with pytest.raises(IntegrityError), transaction.atomic():
        ReviewDecision.objects.create(
            review_item=item,
            reviewer=technician_user,
            action_taken=ReviewAction.APPROVE.value,
            time_spent_sec=1,
            decided_via="agent",
        )


def test_a_runbook_refuses_an_approval_not_made_by_a_person(
    technician_user, employee_user, monkeypatch
):
    item = runbook_item(employee_user)
    ReviewDecision.objects.create(
        review_item=item,
        reviewer=technician_user,
        action_taken=ReviewAction.APPROVE.value,
        time_spent_sec=1,
    )
    monkeypatch.setattr(
        ReviewDecision, "decided_via", property(lambda self: "agent", lambda self, value: None)
    )

    with pytest.raises(RunbookError) as refused:
        runbooks.approval_of(item)

    assert refused.value.code.value == "approver_not_a_person"


def test_audit_rows_inside_a_context_carry_its_fields():
    with audit_context({"via": "agent", "agent_turn_id": "t-1"}):
        inside = AuditLog.objects.record("x", actor_type="human", payload={"a": 1})
    outside = AuditLog.objects.record("y", actor_type="human", payload={"a": 1})

    assert inside.payload == {"a": 1, "via": "agent", "agent_turn_id": "t-1"}
    assert outside.payload == {"a": 1}


def test_a_malformed_action_id_is_refused(technician_user, employee_user):
    item = runbook_item(employee_user)

    response = api_client_for(technician_user).post(
        f"/api/review/items/{item.id}/claim", HTTP_X_AGENT_ACTION=str(uuid.uuid4())[:8]
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_action_not_pending"
