"""Every route's agent tier, and what an agent token may do at each (F15 §h.3, AC-F15-04)."""

from __future__ import annotations

import re
import uuid

import pytest

from apps.accounts.permissions import AgentTier, Gate, gate_of
from apps.accounts.testing import api_client_for
from apps.agent.models import AgentAction, AgentActionKind, AgentActionState, AgentTargetKind
from apps.agent.testing import as_agent, runbook_item
from apps.audit.models import AuditLog
from apps.itsm_mock.models import RunbookExecution
from apps.review.models import ReviewDecision
from config.urls import api

pytestmark = pytest.mark.django_db

TIERS = {
    AgentTier.READ: {
        "GET /api/chat/tickets/{public_id}",
        "GET /api/requester/tickets",
        "GET /api/requester/tickets/{public_id}",
        "GET /api/tickets",
        "GET /api/tickets/board",
        "GET /api/tickets/{public_id}/detail",
        "GET /api/tickets/{public_id}/comments",
        "GET /api/tickets/{public_id}/sla",
        "GET /api/tickets/{public_id}",
        "GET /api/review/queue",
        "GET /api/review/items/{item_id}",
        "GET /api/infra/projects",
        "GET /api/infra/servers",
        "GET /api/infra/servers/{server_id}",
        "GET /api/infra/volumes",
        "GET /api/infra/volumes/{volume_id}",
        "GET /api/infra/networks",
        "GET /api/infra/networks/{network_id}",
        "GET /api/infra/alerts",
        "GET /api/infra/alerts/silences",
        "GET /api/infra/catalog",
        "POST /api/infra/metrics/query",
        "POST /api/infra/metrics/promql",
        "POST /api/infra/logs/search",
        "POST /api/infra/traces/search",
        "GET /api/infra/traces/{trace_id}",
        "GET /api/requester/infra/projects",
        "GET /api/requester/infra/servers",
        "GET /api/requester/infra/servers/{server_id}",
        "GET /api/requester/infra/volumes",
        "GET /api/requester/infra/volumes/{volume_id}",
        "GET /api/requester/infra/networks",
        "GET /api/requester/infra/networks/{network_id}",
        "GET /api/requester/infra/alerts",
        "GET /api/requester/infra/alerts/silences",
        "GET /api/requester/infra/catalog",
        "POST /api/requester/infra/metrics/query",
        "POST /api/requester/infra/logs/search",
        "POST /api/requester/infra/traces/search",
        "GET /api/requester/infra/traces/{trace_id}",
    },
    AgentTier.SELF: {
        "POST /api/chat/ask",
        "POST /api/chat/tickets/{public_id}/clarify",
        "POST /api/chat/tickets/{public_id}/create-ticket",
    },
    AgentTier.CONFIRM: {
        "POST /api/requester/tickets/{public_id}/replies",
        "POST /api/requester/tickets/{public_id}/reopen",
        "POST /api/tickets/{public_id}/take",
        "POST /api/tickets/{public_id}/comments",
        "POST /api/review/items/{item_id}/claim",
        "POST /api/infra/servers/{server_id}/reboot",
        "POST /api/infra/servers/{server_id}/start",
        "POST /api/infra/servers/{server_id}/stop",
        "POST /api/infra/volumes/{volume_id}/attach",
        "POST /api/requester/infra/servers/{server_id}/reboot",
        "POST /api/requester/infra/servers/{server_id}/start",
        "POST /api/requester/infra/servers/{server_id}/stop",
    },
    AgentTier.HUMAN_ONLY: {
        "POST /api/review/items/{item_id}/decide",
        "POST /api/review/items/{item_id}/comment-decision",
        "POST /api/itsm/review-items/{item_id}/execute",
        "POST /api/itsm/executions/{execution_id}/resolve",
        "POST /api/tickets/{public_id}/reassign",
        "PATCH /api/tickets/{public_id}/priority",
        "POST /api/tickets/{public_id}/sla/rebuild",
        "POST /api/tickets/{public_id}/quarantine/reveal",
        "POST /api/infra/servers/{server_id}/hard-reboot",
        "POST /api/infra/volumes/{volume_id}/detach",
        "POST /api/infra/security-groups/{group_id}/rules",
        "DELETE /api/infra/security-groups/{group_id}/rules",
    },
}

# What an action on each `confirm` and `human_only` route is about (F16 BR-F16-05, F17 §g).
TARGETS = {
    "POST /api/requester/tickets/{public_id}/replies": AgentTargetKind.TICKET,
    "POST /api/requester/tickets/{public_id}/reopen": AgentTargetKind.TICKET,
    "POST /api/tickets/{public_id}/take": AgentTargetKind.TICKET,
    "POST /api/tickets/{public_id}/comments": AgentTargetKind.TICKET,
    "POST /api/review/items/{item_id}/claim": AgentTargetKind.REVIEW_ITEM,
    "POST /api/infra/servers/{server_id}/reboot": AgentTargetKind.SERVER,
    "POST /api/infra/servers/{server_id}/start": AgentTargetKind.SERVER,
    "POST /api/infra/servers/{server_id}/stop": AgentTargetKind.SERVER,
    "POST /api/infra/volumes/{volume_id}/attach": AgentTargetKind.VOLUME,
    "POST /api/requester/infra/servers/{server_id}/reboot": AgentTargetKind.SERVER,
    "POST /api/requester/infra/servers/{server_id}/start": AgentTargetKind.SERVER,
    "POST /api/requester/infra/servers/{server_id}/stop": AgentTargetKind.SERVER,
    "POST /api/review/items/{item_id}/decide": AgentTargetKind.REVIEW_ITEM,
    "POST /api/review/items/{item_id}/comment-decision": AgentTargetKind.REVIEW_ITEM,
    "POST /api/itsm/review-items/{item_id}/execute": AgentTargetKind.REVIEW_ITEM,
    "POST /api/itsm/executions/{execution_id}/resolve": AgentTargetKind.RUNBOOK_EXECUTION,
    "POST /api/tickets/{public_id}/reassign": AgentTargetKind.TICKET,
    "PATCH /api/tickets/{public_id}/priority": AgentTargetKind.TICKET,
    "POST /api/tickets/{public_id}/sla/rebuild": AgentTargetKind.TICKET,
    "POST /api/tickets/{public_id}/quarantine/reveal": AgentTargetKind.TICKET,
    "POST /api/infra/servers/{server_id}/hard-reboot": AgentTargetKind.SERVER,
    "POST /api/infra/volumes/{volume_id}/detach": AgentTargetKind.VOLUME,
    "POST /api/infra/security-groups/{group_id}/rules": AgentTargetKind.SECURITY_GROUP,
    "DELETE /api/infra/security-groups/{group_id}/rules": AgentTargetKind.SECURITY_GROUP,
}


def gates() -> dict[str, Gate]:
    found: dict[str, Gate] = {}
    for prefix, router in api._routers:
        for path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                gate = gate_of(operation.view_func)
                if gate is None:
                    continue
                for method in operation.methods:
                    found[f"{method} /api{prefix.rstrip('/')}{path}"] = gate
    return found


def gated_routes() -> dict[str, AgentTier | None]:
    return {key: gate.agent_tier for key, gate in gates().items()}


def test_every_gated_route_declares_an_agent_tier():
    undeclared = sorted(key for key, tier in gated_routes().items() if tier is None)

    assert undeclared == []


def test_only_the_routes_the_spec_names_admit_an_agent():
    routes = gated_routes()

    for tier, expected in TIERS.items():
        assert {key for key, t in routes.items() if t is tier} == expected, tier


def test_every_confirm_and_human_only_route_declares_its_target():
    held = {
        key: gate.target
        for key, gate in gates().items()
        if gate.agent_tier in (AgentTier.CONFIRM, AgentTier.HUMAN_ONLY)
    }

    assert held == TARGETS
    for key in held:
        assert len(re.findall(r"\{[^}]+\}", key)) == 1, f"{key} names its target by one parameter"


def test_only_a_route_that_holds_actions_declares_a_target():
    declared = {key for key, gate in gates().items() if gate.target is not None}

    assert declared == set(TARGETS)


def test_a_read_route_answers_an_agent_as_its_user(employee_user):
    response = as_agent(employee_user, "list_my_tickets").get("/api/requester/tickets")

    assert response.status_code == 200


def test_a_self_route_runs_and_stamps_its_audit_rows(employee_user, monkeypatch):
    async def ner_finds_nothing(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.domain.masking.llm_ner", ner_finds_nothing)
    monkeypatch.setattr(
        "apps.tickets.tasks.process_ticket", type("Fake", (), {"delay": lambda self, i: None})()
    )
    turn = uuid.uuid4()

    response = as_agent(employee_user, "ask_helpdesk", turn).post(
        "/api/chat/ask",
        {"message": "VPN drops every ~10 min since this morning"},
        content_type="application/json",
    )

    assert response.status_code == 200
    row = AuditLog.objects.get(event="ticket_submitted")
    assert row.actor_id == employee_user.id
    assert row.payload["via"] == "agent"
    assert row.payload["agent_turn_id"] == str(turn)
    assert row.payload["agent_tool"] == "ask_helpdesk"


def test_a_human_only_route_stores_a_draft_and_runs_nothing(technician_user, employee_user):
    item = runbook_item(employee_user)

    response = as_agent(technician_user).post(
        f"/api/review/items/{item.id}/decide",
        {"action_taken": "approve", "time_spent_sec": 0},
        content_type="application/json",
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "human_only_action"
    assert body["message"] == "human-only action"
    draft = AgentAction.objects.get(id=body["details"]["draft_id"])
    assert draft.kind == AgentActionKind.DRAFT.value
    assert draft.state == AgentActionState.PENDING.value
    assert (draft.target_kind, draft.target_ref) == ("review_item", str(item.id))
    assert not ReviewDecision.objects.filter(review_item=item).exists()
    assert not RunbookExecution.objects.filter(review_item=item).exists()
    item.refresh_from_db()
    assert item.state == "pending"
    row = AuditLog.objects.get(event="agent_draft_created")
    assert row.actor_id == technician_user.id
    assert row.payload["via"] == "agent"
    assert row.payload["agent_action_id"] == str(draft.id)


def test_a_confirm_route_stores_the_call_and_answers_202(technician_user, employee_user):
    item = runbook_item(employee_user)

    response = as_agent(technician_user, "claim_review_item").post(
        f"/api/review/items/{item.id}/claim"
    )

    assert response.status_code == 202
    action = AgentAction.objects.get(id=response.json()["action_id"])
    assert response.json()["state"] == "awaiting_confirmation"
    assert action.kind == AgentActionKind.CONFIRM.value
    assert action.tool == "claim_review_item"
    item.refresh_from_db()
    assert item.state == "pending"
    assert AuditLog.objects.filter(event="agent_action_proposed").count() == 1


def test_a_person_still_calls_every_tiered_route_as_before(technician_user, employee_user):
    item = runbook_item(employee_user)

    response = api_client_for(technician_user).post(f"/api/review/items/{item.id}/claim")

    assert response.status_code == 200
    assert not AgentAction.objects.exists()
