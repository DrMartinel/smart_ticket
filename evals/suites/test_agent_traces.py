"""
The F15 agent's acceptance traces (spec F15 §j, AC-F15-01..05, and the 2026-11-26 amendment's
AC-F15-11..15 and EC-F15-09), run end to end in one process: core-api takes the message and runs
the turn, ai-engine's agent graph answers it with a scripted model, and every tool call goes back
into core-api with the turn's agent token.
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
from ai_engine.graph.agent_state import AgentChoice as EngineChoice
from ai_engine.graph.agent_state import AgentStopReason as EngineStopReason
from ai_engine.main import agent_turn as engine_agent_turn
from ai_engine.schemas import AgentTurnRequest as EngineTurnRequest
from ai_engine.schemas import AgentTurnResponse as EngineTurnResponse
from apps.accounts.models import User
from apps.accounts.permissions import gate_of
from apps.accounts.testing import agent_token_for, api_client_for
from apps.agent.models import AgentAction, AgentTurn
from apps.agent.testing import runbook_item
from apps.agent.services.turns import agent_turns
from apps.audit.models import AuditLog
from apps.incidents.services.incidents import incidents
from apps.itsm_mock.models import RunbookExecution
from apps.review.models import ReviewDecision
from apps.tickets import tasks as ticket_tasks
from apps.tickets.models import IncidentVerdict, Ticket
from apps.tickets.testing import nothing_found
from config.urls import api
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import AgentChoice, AgentStopReason, AgentTurnResponse, AIRunResponse

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

    def __init__(self, on_wait: Callable[[], bool]) -> None:
        self.client = Client(raise_request_exception=False)
        self.on_wait = on_wait
        self.calls: list[tuple[str, str, int]] = []

    def send(self, method, path, token, tool, *, read, params=None, json=None):
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
            if read:
                raise ToolFailed(f"HTTP {response.status_code}")
            raise OutcomeUnknown(f"HTTP {response.status_code}")
        try:
            body = response.json() if response.content else None
        except ValueError as err:
            raise ToolFailed("unparseable reply") from err
        return Reply(response.status_code, body)

    def wait(self, seconds):
        if not self.on_wait():
            raise AssertionError("ask_helpdesk is waiting on a ticket no pipeline will decide")


class Stack:
    """core-api and ai-engine in one process: the agent's model, its tool client, the queues."""

    def __init__(self, monkeypatch, capture_on_commit) -> None:
        self.monkeypatch = monkeypatch
        self.capture_on_commit = capture_on_commit
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
            ai_engine, "analyze", lambda masked, request_id, categories: _no_proposal(request_id)
        )

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/embed":
                return httpx.Response(200, json={"vector": [1.0] + [0.0] * 1023, "model": "trace"})
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

    def run_pipelines(self) -> bool:
        """Runs each ticket pipeline queued so far, as the Celery worker would; False when none was."""
        ran = bool(self.queued_tickets)
        while self.queued_tickets:
            self._real_process.apply(args=(self.queued_tickets.pop(0),), throw=True)
        return ran

    def send(
        self,
        user: User,
        message: str,
        surface: str = "chat",
        conversation: uuid.UUID | None = None,
    ) -> AgentTurn:
        """The person's message to the agent, through core-api's own route, then the turn's run."""
        body: dict[str, Any] = {"message": message, "surface": surface}
        if conversation is not None:
            body["conversation_id"] = str(conversation)
        with self.capture_on_commit(execute=True):
            response = api_client_for(user).post(
                "/api/agent/turns", body, content_type="application/json"
            )
        assert response.status_code == 202, response.content
        turn_id = response.json()["turn_id"]
        assert self.queued_turns == [turn_id]
        agent_turns.run(uuid.UUID(self.queued_turns.pop()))
        self.run_pipelines()
        return AgentTurn.objects.get(id=turn_id)


def _no_proposal(request_id: str) -> AIRunResponse:
    """ai-engine's triage with nothing found: the router refuses before any proposal."""
    return AIRunResponse(
        request_id=request_id,
        graph_version="trace",
        prompt_version="trace",
        model="n/a",
        proposal=None,
        signals=nothing_found(),
    )


def call(tool: str, **arguments: Any) -> dict[str, Any]:
    return {"action": "call_tool", "tool": tool, "arguments": arguments}


def reply(text: str) -> dict[str, Any]:
    return {"action": "reply", "text": text}


def choose(text: str, *refs: str) -> dict[str, Any]:
    return {"action": "reply", "text": text, "proposed_choices": list(refs)}


def hand_off(text: str, summary: str) -> dict[str, Any]:
    return {"action": "hand_off", "text": text, "proposed_handoff_summary": summary}


@pytest.fixture
def stack(monkeypatch, db, django_capture_on_commit_callbacks) -> Iterator[Stack]:
    built = Stack(monkeypatch, django_capture_on_commit_callbacks)
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
        held = Ticket.objects.get()
        assert (held.status, held.held_decision is not None) == ("awaiting_requester", True)
        return call("request_ticket", public_id=held.public_id)

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
    assert (decision.branch, decision.reason_code) == ("hitl", "retrieval_below_floor")
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


# ── AC-F15-05: step limit ──


@pytest.mark.django_db
def test_ac_f15_05_a_turn_at_the_step_limit_hands_off_to_the_router(stack, linh, monkeypatch):
    limits = django_settings.THRESHOLDS.agent
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
    assert turn.handoff_ticket is None and turn.offers_ticket()
    opened = api_client_for(linh).post(f"/api/agent/turns/{turn.id}/ticket")
    assert opened.status_code == 200, opened.content
    stack.run_pipelines()
    turn.refresh_from_db()
    ticket = turn.handoff_ticket
    assert ticket is not None
    assert ticket.agent_handoff_reason == "agent_step_limit"
    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_step_limit")


# ── The 2026-11-26 amendment: the agent finds out, asks, and says why ──

FOLDER = "Give me access to the Finance Reports folder"
FOLDER_TEXT = (
    "Folder access is granted by IT after your manager approves it; I can't grant it here."
)
SUMMARY = "Asks for access to the Finance Reports folder"


def vpn_tickets(reporter: User) -> None:
    """Two open VPN tickets of `reporter`."""
    for public_id, subject in (
        ("TKT-2026-000415", "VPN TLS handshake error"),
        ("TKT-2026-000437", "VPN drops every 10 minutes"),
    ):
        Ticket.objects.create(
            public_id=public_id,
            reporter=reporter,
            subject_masked=subject,
            body_masked=subject,
            pii_level="routine",
        )


@pytest.mark.django_db
def test_ac_f15_11_a_choice_the_turn_never_fetched_is_refused(stack, linh):
    vpn_tickets(linh)
    model = stack.script(
        call("list_my_tickets"),
        choose("Which one?", "item_1", "item_7"),
        choose("Which one?", "item_1", "item_7"),
    )

    turn = stack.send(linh, "What happened to my VPN ticket?")

    assert len(model.prompts) == 3
    assert "item_7" in model.prompts[2]
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_schema_invalid")
    assert turn.choices is None


@pytest.mark.django_db
def test_ac_f15_12_a_card_always_lets_the_person_say_something_else(stack, linh):
    vpn_tickets(linh)
    stack.script(call("list_my_tickets"), choose("Which one?", "item_1", "item_2"))

    asked = stack.send(linh, "What happened to my VPN ticket?")

    assert asked.state == "replied", asked.stop_reason
    card = api_client_for(linh).get(f"/api/agent/turns/{asked.id}").json()["choices"]
    assert sorted(c["id"] for c in card[:2]) == ["TKT-2026-000415", "TKT-2026-000437"]
    assert {c["label"] for c in card[:2]} == {
        "TKT-2026-000415 · VPN TLS handshake error",
        "TKT-2026-000437 · VPN drops every 10 minutes",
    }
    assert card[2] == {"kind": "something_else", "id": None, "label": "Something else"}


@pytest.mark.django_db
def test_pressing_a_choice_sends_its_label(stack, linh):
    vpn_tickets(linh)
    stack.script(call("list_my_tickets"), choose("Which one?", "item_1", "item_2"))
    asked = stack.send(linh, "What happened to my VPN ticket?")
    pressed = asked.choices[1]
    model = stack.script(
        call("get_my_ticket", public_id=pressed["id"]), reply("It is waiting for the team.")
    )

    answered = stack.send(linh, pressed["label"], conversation=asked.conversation_id)

    assert answered.state == "replied", answered.stop_reason
    assert (answered.conversation_id, answered.seq) == (asked.conversation_id, asked.seq + 1)
    assert answered.message_masked == pressed["label"]
    assert f"[choice] {asked.choices[0]['label']}" in model.prompts[0]
    assert "Something else" not in model.prompts[0]


@pytest.mark.django_db
def test_ac_f15_13_a_change_the_chat_can_t_make_is_explained_and_offered_as_a_ticket(stack, linh):
    stack.script(hand_off(FOLDER_TEXT, SUMMARY))

    turn = stack.send(linh, FOLDER)

    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_needs_staff")
    shown = api_client_for(linh).get(f"/api/agent/turns/{turn.id}").json()
    assert (shown["reply"], shown["ticket_offered"]) == (FOLDER_TEXT, True)
    assert shown["needs_staff"] == {"checked": None, "button": "Open a ticket", "opened": None}
    assert SUMMARY not in dumps(shown)


@pytest.mark.django_db
def test_ac_f15_14_the_ticket_keeps_the_person_s_words_and_the_summary_stays_with_staff(
    stack, linh, monkeypatch
):
    sent: list[str] = []

    def analyze(masked, request_id, categories):
        sent.append(masked.model_dump_json())
        return _no_proposal(request_id)

    monkeypatch.setattr(ai_engine, "analyze", analyze)
    stack.script(call("list_my_tickets"), hand_off(FOLDER_TEXT, SUMMARY))
    turn = stack.send(linh, FOLDER)

    opened = api_client_for(linh).post(f"/api/agent/turns/{turn.id}/ticket")
    stack.run_pipelines()

    assert opened.status_code == 200, opened.content
    ticket = Ticket.objects.get()
    assert opened.json()["needs_staff"] == {
        "checked": "What I checked above goes with the ticket, so you won't need to explain again.",
        "button": "Open a ticket",
        "opened": f"Opened ticket {ticket.public_id}. You can follow it under My tickets.",
    }
    assert (ticket.subject_masked, ticket.body_masked) == (FOLDER, FOLDER)
    assert (ticket.agent_handoff_reason, ticket.proposed_handoff_summary) == (
        "agent_needs_staff",
        SUMMARY,
    )
    (request,) = sent
    assert SUMMARY not in request
    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_needs_staff")


@pytest.mark.django_db
def test_ac_f15_15_staff_can_t_hand_off_on_purpose(stack, minh):
    model = stack.script(hand_off(FOLDER_TEXT, SUMMARY), repeat_last=True)

    turn = stack.send(minh, "Give linh access to the Finance Reports folder", surface="console")

    assert len(model.prompts) == 2
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_schema_invalid")
    assert turn.reply_text != FOLDER_TEXT and turn.proposed_handoff_summary is None


@pytest.mark.django_db
def test_ec_f15_09_a_laptop_that_won_t_reach_vpn_goes_to_the_helpdesk(stack, linh):
    stack.script(
        call("ask_helpdesk", message="My laptop won't connect to VPN."),
        reply("The helpdesk's answer is below."),
    )

    turn = stack.send(linh, "My laptop won't connect to VPN.")

    assert turn.state == "replied", turn.stop_reason
    assert [(r["tool"], r["outcome"]) for r in turn.receipts] == [("ask_helpdesk", "done")]


def test_stop_reasons_match_in_both_services():
    assert {r.value for r in EngineStopReason} == {r.value for r in AgentStopReason}


def test_the_turn_result_and_its_choices_have_the_same_fields_in_both_services():
    assert set(EngineTurnResponse.model_fields) == set(AgentTurnResponse.model_fields)
    assert set(EngineChoice.model_fields) == set(AgentChoice.model_fields)
