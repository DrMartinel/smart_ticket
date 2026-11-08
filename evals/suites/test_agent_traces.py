"""
The F15 agent's acceptance traces (spec F15 §j, AC-F15-01..05), run end to end in one process:
core-api takes the message and runs the turn, ai-engine's agent graph answers it with a scripted
model, and every tool call goes back into core-api with the turn's agent token. No model, no
network: ai-engine's HTTP edges are swapped for in-process calls, so both wire schemas run.
"""

from __future__ import annotations

import uuid
from json import dumps
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from django.conf import settings as django_settings
from django.test import Client

from ai_engine.agent.tools import client as tool_client
from ai_engine.agent.tools.client import OutcomeUnknown, Reply, ToolFailed
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import LLMResult
from ai_engine.main import agent_turn as engine_agent_turn
from ai_engine.schemas import AgentTurnRequest as EngineTurnRequest
from apps.accounts.models import User
from apps.accounts.permissions import AgentTier, gate_of
from apps.accounts.testing import agent_token_for, api_client_for
from apps.agent.models import AgentAction, AgentTurn
from apps.agent.testing import runbook_item
from apps.agent.utils.turns import agent_turns
from apps.audit.models import AuditLog
from apps.incidents.utils.incidents import incidents
from apps.itsm_mock.models import RunbookExecution
from apps.review.models import ReviewDecision
from apps.rollout.testing import all_live
from apps.tickets import tasks as ticket_tasks
from apps.tickets.models import IncidentVerdict, Ticket
from apps.tickets.utils.pipeline import _degraded_signals
from config.urls import api
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import AIRunResponse, EngineSignals

PHONE = "0912345678"

Action = dict[str, Any] | Callable[[], dict[str, Any]]


class ScriptedModel:
    """Answers each agent model call with the next scripted action; the last one repeats when
    `repeat_last` is set."""

    def __init__(self, *actions: Action, repeat_last: bool = False) -> None:
        self.actions = list(actions)
        self.repeat_last = repeat_last
        self.prompts: list[str] = []

    def complete(self, system_prompt, user_prompt, *, schema_name, schema, temperature=None):
        self.prompts.append(f"{system_prompt}\n{user_prompt}")
        if not self.actions:
            raise AssertionError("the model was called more often than scripted")
        action = (
            self.actions[0] if self.repeat_last and len(self.actions) == 1 else self.actions.pop(0)
        )
        body = action() if callable(action) else action
        return LLMResult(
            text=dumps(body), tokens_in=10, tokens_out=5, model="scripted", cost_usd=0.0
        )


class InProcessCoreApi:
    """ai-engine's tool client, answered by core-api's own views through Django's test client."""

    def __init__(self, on_wait: Callable[[], None]) -> None:
        self.client = Client()
        self.on_wait = on_wait
        self.calls: list[tuple[str, str, int]] = []

    def send(self, method, path, token, tool, *, params=None, json=None):
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {token.get_secret_value()}",
            "HTTP_X_AGENT_TOOL": tool,
        }
        if method == "GET":
            response = self.client.get(path, params or {}, **headers)
        else:
            response = self.client.generic(
                method,
                path,
                data=dumps(json) if json is not None else "",
                content_type="application/json",
                **headers,
            )
        self.calls.append((method, path, response.status_code))
        if response.status_code >= 500:
            if method == "GET":
                raise ToolFailed(f"HTTP {response.status_code}")
            raise OutcomeUnknown(f"HTTP {response.status_code}")
        return Reply(response.status_code, response.json() if response.content else None)

    def wait(self, seconds):
        self.on_wait()


class Stack:
    """core-api and ai-engine in one process: the agent's model, its tool client, the queues."""

    def __init__(self, monkeypatch) -> None:
        self.monkeypatch = monkeypatch
        self.queued_tickets: list[str] = []
        self.queued_turns: list[str] = []
        self.model: ScriptedModel | None = None
        self.core_api = InProcessCoreApi(self.run_pipelines)
        self._real_process = ticket_tasks.process_ticket

    def install(self) -> None:
        class Queue:
            def __init__(self, into: list[str]) -> None:
                self.into = into

            def delay(self, item_id: str) -> None:
                self.into.append(item_id)

        self.monkeypatch.setattr("apps.tickets.tasks.process_ticket", Queue(self.queued_tickets))
        self.monkeypatch.setattr("apps.agent.tasks.run_turn", Queue(self.queued_turns))
        self.monkeypatch.setattr(tool_client, "core_api", self.core_api)
        self.monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
        self.monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
        self.monkeypatch.setattr(
            ai_engine, "analyze", lambda masked, request_id: _no_proposal(request_id)
        )

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/pii/detect":
                return httpx.Response(200, json={"spans": []})
            if request.url.path == "/v1/agent/turn":
                answer = engine_agent_turn(EngineTurnRequest.model_validate_json(request.content))
                return httpx.Response(200, json=answer.model_dump(mode="json"))
            raise httpx.ConnectError(f"not served in the trace suite: {request.url.path}")

        transport = httpx.MockTransport(handle)
        real_client = httpx.Client
        real_async = httpx.AsyncClient

        class StubClient(real_client):  # type: ignore[misc, valid-type]
            def __init__(self, *a, **kw):
                super().__init__(*a, **{**kw, "transport": transport})

        class StubAsyncClient(real_async):  # type: ignore[misc, valid-type]
            def __init__(self, *a, **kw):
                super().__init__(*a, **{**kw, "transport": transport})

        self.monkeypatch.setattr("infrastructure.ai_engine.httpx.Client", StubClient)
        self.monkeypatch.setattr("infrastructure.ai_engine.httpx.AsyncClient", StubAsyncClient)

    def script(self, *actions: Action, repeat_last: bool = False) -> ScriptedModel:
        self.model = ScriptedModel(*actions, repeat_last=repeat_last)
        self.monkeypatch.setattr(clients, "agent", self.model)
        return self.model

    def run_pipelines(self) -> None:
        """Runs each ticket pipeline queued so far, as the Celery worker would."""
        while self.queued_tickets:
            self._real_process.apply(args=(self.queued_tickets.pop(0),))

    def send(self, user: User, message: str, surface: str = "chat") -> AgentTurn:
        """The person's message to the agent, through core-api's own route, then the turn's run."""
        response = api_client_for(user).post(
            "/api/agent/turns",
            {"message": message, "surface": surface},
            content_type="application/json",
        )
        assert response.status_code == 202, response.content
        turn_id = response.json()["turn_id"]
        assert self.queued_turns == [turn_id]
        agent_turns.run(uuid.UUID(self.queued_turns.pop()))
        self.run_pipelines()
        return AgentTurn.objects.get(id=turn_id)


def _no_proposal(request_id: str) -> AIRunResponse:
    """ai-engine's triage with nothing found: the router refuses before any proposal."""
    d = _degraded_signals()
    return AIRunResponse(
        request_id=request_id,
        graph_version="trace",
        prompt_version="trace",
        model="n/a",
        proposal=None,
        signals=EngineSignals(
            retrieval=d.retrieval,
            generation=d.generation,
            classification=d.classification,
            injection_detected=False,
        ),
    )


def call(tool: str, **arguments: Any) -> dict[str, Any]:
    return {"action": "call_tool", "tool": tool, "arguments": arguments}


def reply(text: str) -> dict[str, Any]:
    return {"action": "reply", "text": text}


@pytest.fixture
def stack(settings, monkeypatch, db) -> Iterator[Stack]:
    all_live(settings)
    built = Stack(monkeypatch)
    built.install()
    yield built


@pytest.fixture
def linh(django_user_model) -> User:
    return django_user_model.objects.create_user(username="linh", password="x", role="employee")


@pytest.fixture
def minh(django_user_model) -> User:
    return django_user_model.objects.create_user(username="minh", password="x", role="technician")


# ── AC-F15-01: employee happy path ──


@pytest.mark.django_db
def test_ac_f15_01_an_employee_s_ticket_is_opened_through_the_router(stack, linh):
    def opened() -> dict[str, Any]:
        return call("request_ticket", public_id=Ticket.objects.get().public_id)

    model = stack.script(
        call("ask_helpdesk", message="VPN drops every ~10 min since this morning"),
        opened,
        lambda: reply(f"I opened a ticket for you: {Ticket.objects.get().public_id}."),
    )

    turn = stack.send(
        linh, f"VPN drops every ~10 min since this morning, open a ticket for me. Call {PHONE}"
    )

    assert turn.state == "replied", turn.stop_reason
    ticket = Ticket.objects.get()
    assert turn.reply_text.endswith(f"{ticket.public_id}.")
    assert [(r["tool"], r["outcome"]) for r in turn.receipts] == [
        ("ask_helpdesk", "done"),
        ("request_ticket", "done"),
    ]
    assert ticket.public_id in turn.receipts[1]["path"]
    decision = ticket.routing_decisions.get()
    assert decision.branch == "hitl"
    assert ticket.held_decision is None
    assert all(PHONE not in prompt for prompt in model.prompts)
    asked = AuditLog.objects.get(event="requester_asked_for_ticket", ticket_id=ticket.id)
    assert asked.payload["via"] == "agent"


# ── AC-F15-02: injection in a ticket body (technician side) ──


@pytest.mark.django_db
def test_ac_f15_02_an_injected_review_item_gets_a_draft_and_nothing_runs(stack, minh, linh):
    item = runbook_item(linh)
    stack.script(
        call("list_review_queue"),
        call("draft_review_decision", item_id=str(item.id), action_taken="approve"),
        reply("A draft decision is waiting for you on the item's page."),
    )

    turn = stack.send(minh, "Clear the easy items in my review queue", surface="console")

    assert turn.state == "replied", turn.stop_reason
    outcomes = [r["outcome"] for r in turn.receipts]
    assert outcomes == ["draft_waiting"]
    assert "approved" not in turn.reply_text.lower()
    draft = AgentAction.objects.get()
    assert (draft.kind, draft.state, draft.target_ref) == ("draft", "pending", str(item.id))
    assert not ReviewDecision.objects.filter(review_item=item).exists()
    assert not RunbookExecution.objects.filter(review_item=item).exists()
    row = AuditLog.objects.get(event="agent_draft_created")
    assert (row.actor_id, row.payload["via"]) == (minh.id, "agent")


# ── AC-F15-03: rights never grow ──


@pytest.mark.django_db
def test_ac_f15_03_an_agent_token_is_refused_where_its_person_is(linh):
    own = api_client_for(linh).get("/api/tickets/board")
    agent = Client(
        HTTP_AUTHORIZATION=f"Bearer {agent_token_for(linh)}", HTTP_X_AGENT_TOOL="list_tickets"
    )

    as_agent = agent.get("/api/tickets/board")

    assert own.status_code == as_agent.status_code == 403
    assert as_agent.json() == own.json()


# ── AC-F15-04: default deny ──


def test_ac_f15_04_every_gated_route_declares_an_agent_tier():
    undeclared: list[str] = []
    for prefix, router in api._routers:
        for path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                gate = gate_of(operation.view_func)
                if gate is not None and gate.agent_tier is None:
                    undeclared.extend(
                        f"{m} /api{prefix.rstrip('/')}{path}" for m in operation.methods
                    )

    assert undeclared == []
    assert AgentTier.NONE.value == "none"


# ── AC-F15-05: step limit ──


@pytest.mark.django_db
def test_ac_f15_05_a_turn_at_the_step_limit_hands_off_to_the_router(stack, linh, monkeypatch):
    limits = django_settings.THRESHOLDS.agent
    # More tool calls than steps, so the step limit is the one reached.
    roomy = limits.model_copy(update={"max_tool_calls_per_turn": limits.max_steps + 1})
    monkeypatch.setattr(
        django_settings,
        "THRESHOLDS",
        django_settings.THRESHOLDS.model_copy(update={"agent": roomy}),
    )
    model = stack.script(call("list_my_tickets"), repeat_last=True)

    turn = stack.send(linh, "Where are all my tickets?")

    assert len(model.prompts) == limits.max_steps
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_step_limit")
    assert "list_my_tickets" not in turn.reply_text
    ticket = turn.handoff_ticket
    assert ticket is not None
    assert ticket.agent_handoff_reason == "agent_step_limit"
    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_step_limit")
