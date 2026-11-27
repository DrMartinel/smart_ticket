"""
The agent's acceptance traces, run end to end in one process: core-api takes the message and runs
the turn, ai-engine's agent graph answers it with a scripted model, and every tool call goes back
into core-api with the turn's agent token. F15's (spec F15 §j, AC-F15-01..05; the 2026-11-26
amendment's AC-F15-11..15 and EC-F15-01..10) and F17's (§j, AC-F17-01..09), whose cloud is
cloud-sim in-process with fakes for Prometheus, Elasticsearch and Alertmanager.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, time, timedelta
from json import dumps, loads
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cloud_sim.faults import FaultKind
from cloud_sim.telemetry.signals import _INJECTION as INJECTED_LOG_LINE
from django.conf import settings as django_settings
from django.test import Client

from ai_engine.agent.tools import TOOLS
from ai_engine.agent.tools import client as tool_client
from ai_engine.agent.tools.client import OutcomeUnknown, Reply, ToolFailed
from ai_engine.core.config import settings as engine_settings
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import LLMResult
from ai_engine.graph.agent_state import AgentChoice as EngineChoice
from ai_engine.graph.agent_state import AgentLimits as EngineLimits
from ai_engine.graph.agent_state import AgentStep as EngineStep
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
from apps.infra.domain.catalog import PROJECT_FIELD
from apps.infra.domain.untrusted import WITHHELD
from apps.infra.tests import conftest as infra_fakes
from apps.infra.tests import test_promql as promql_trees
from apps.infra.tests.conftest import LAN_SUBJECT, log_doc, series
from apps.itsm_mock.models import RunbookExecution
from apps.lifecycle.tests.conftest import make_ticket
from apps.review.models import ReviewDecision
from apps.tickets import tasks as ticket_tasks
from apps.tickets.domain.masking import NERError
from apps.tickets.models import IncidentVerdict, Ticket
from apps.tickets.testing import nothing_found
from config.urls import api
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import (
    AgentChoice,
    AgentLimits,
    AgentStep,
    AgentStopReason,
    AgentTurnResponse,
    AIRunResponse,
)

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

    def send(self, method, path, token, tool, *, read, step, params=None, json=None):
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {token.get_secret_value()}",
            "HTTP_X_AGENT_TOOL": tool,
        }
        if step is not None:
            headers["HTTP_X_AGENT_STEP"] = str(step)
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


def test_every_tool_s_tier_is_its_route_s():
    """ADR-0046 §5: ai-engine reads a call's failure by its tool's tier; core-api's gate holds
    the tier that decides."""

    def shape(path: str) -> str:
        return re.sub(r"\{[^}]*\}", "{}", path)

    tiers: dict[tuple[str, str], str | None] = {}
    for prefix, router in api._routers:
        for path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                gate = gate_of(operation.view_func)
                tier = gate.agent_tier.value if gate and gate.agent_tier else None
                for method in operation.methods:
                    tiers[(method, shape(f"/api{prefix.rstrip('/')}{path}"))] = tier

    found = {name: tiers.get((t.method, shape(t.path)), "no route") for name, t in TOOLS.items()}
    assert {n: f for n, f in found.items() if f != TOOLS[n].tier.value} == {}


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
    assert set(EngineStep.model_fields) == set(AgentStep.model_fields)
    assert set(EngineLimits.model_fields) == set(AgentLimits.model_fields)


# ── F17: the agent reads the cloud and proposes changes ──

# cloud-sim in-process as the cloud, and the infra tests' Prometheus, Elasticsearch, Alertmanager
# and NER fakes, as fixtures of this suite.
cloud_sim = infra_fakes.cloud_sim
prom = infra_fakes.prom
es = infra_fakes.es
alertmanager = infra_fakes.alertmanager
backends = infra_fakes.backends
ner = infra_fakes.ner

START, END = "2026-11-26T08:00:00+00:00", "2026-11-26T10:00:00+00:00"
ES_DOWN = "Elasticsearch was unreachable; this answer has no logs or traces."
CHECKED = "What I checked above goes with the ticket, so you won't need to explain again."
WRITES = frozenset(name for name, tool in TOOLS.items() if tool.writes)


@pytest.fixture
def lan(django_user_model) -> User:
    """lan.nt of Sao Mai Logistics, whose Keystone user is a member of saomai-prod and
    saomai-staging."""
    return django_user_model.objects.create_user(
        username="lan.nt", password="x", role="employee", external_id=LAN_SUBJECT
    )


@pytest.fixture
def duc(django_user_model) -> User:
    """duc.tm, a technician."""
    return django_user_model.objects.create_user(username="duc.tm", password="x", role="technician")


def open_ticket(reporter: User) -> Ticket:
    """TKT-2026-000431, an open ticket of `reporter` past triage."""
    ticket = make_ticket(reporter)
    Ticket.objects.filter(pk=ticket.pk).update(public_id="TKT-2026-000431")
    ticket.refresh_from_db()
    return ticket


def did(prompt: str) -> list[dict[str, Any]]:
    """The calls a step's prompt says the turn made so far, each with what the model was shown."""
    if "## What you did this turn\n" not in prompt:
        return []
    return loads(prompt.split("## What you did this turn\n", 1)[1].split("\n\n## ", 1)[0])


def offered(prompt: str) -> set[str]:
    """The tools a step's prompt offered the model."""
    return {t["name"] for t in loads(prompt.split("## Tools\n", 1)[1].split("\n\n## ", 1)[0])}


def ref_of(prompt: str, name: str) -> str:
    """The ref the turn's results so far gave the resource named `name`."""
    left: list[Any] = did(prompt)
    while left:
        value = left.pop()
        if isinstance(value, dict):
            if value.get("name") == name and "ref" in value:
                return str(value["ref"])
            left.extend(value.values())
        elif isinstance(value, list):
            left.extend(value)
    raise AssertionError(f"no result of the turn gave {name} a ref")


def press(user: User, action: AgentAction) -> Any:
    """`user` confirming the card of `action`, with their own session."""
    return api_client_for(user).post(
        action.path,
        action.arguments["payload"],
        content_type="application/json",
        headers={"X-Agent-Action": str(action.id)},
    )


def shown(user: User, turn: AgentTurn) -> dict[str, Any]:
    """The turn as the person's frontend reads it."""
    return api_client_for(user).get(f"/api/agent/turns/{turn.id}").json()


def scope_of(body: dict[str, Any]) -> list[str]:
    """The projects a compiled Elasticsearch search filters on."""
    (projects,) = [
        f["terms"][PROJECT_FIELD]
        for f in body["query"]["bool"]["filter"]
        if PROJECT_FIELD in f.get("terms", {})
    ]
    return list(projects)


@pytest.mark.django_db
def test_ac_f17_01_a_customer_s_agent_reaches_no_backend_for_another_company(
    stack, lan, cloud_sim, prom, es
):
    web03, hbr = cloud_sim.id_of("servers", "web-03"), cloud_sim.id_of("projects", "hbr-web")
    model = stack.script(
        call("get_my_server", server_id=web03),
        call(
            "query_my_metrics",
            metric="cloud_server_cpu_utilization_ratio",
            start=START,
            end=END,
            step_seconds=60,
            project_id=hbr,
        ),
        call("search_my_logs", start=START, end=END, project_id=hbr),
        reply("web-03 is not one of your servers."),
    )

    turn = stack.send(lan, "Show me the logs for web-03.")

    assert turn.state == "replied", turn.stop_reason
    server, metrics, logs = did(model.prompts[3])
    assert (server["status"], server["result"]["code"]) == (404, "infra_not_found")
    assert (metrics["result"]["series"], logs["result"]["lines"]) == ([], [])
    assert prom.queries == [] and es.searches == []


@pytest.mark.django_db
def test_ac_f17_02_every_log_search_the_customer_s_agent_compiles_carries_her_projects(
    stack, lan, cloud_sim, es
):
    prod = cloud_sim.id_of("projects", "saomai-prod")
    staging = cloud_sim.id_of("projects", "saomai-staging")
    stack.script(
        call("search_my_logs", start=START, end=END, project_id=prod, text="timeout"),
        call("search_my_logs", start=START, end=END, filters={"server": ["db-01"]}),
        reply("No timeouts on db-01 this morning."),
    )

    stack.send(lan, "Any timeouts in my logs this morning?")

    named, unnamed = es.bodies()
    assert scope_of(named) == [prod]
    assert scope_of(unnamed) == sorted([prod, staging])


@pytest.mark.django_db
def test_ac_f17_03_a_match_everything_promql_selector_is_refused_and_never_run(
    stack, duc, cloud_sim, prom
):
    text = 'rate(node_cpu_seconds_total{instance=~".*"}[5m])'
    prom.tree = promql_trees.call(
        "rate",
        promql_trees.ranged(
            promql_trees.vs("node_cpu_seconds_total", promql_trees.m("instance", "=~", ".*")),
            5 * promql_trees.MINUTE,
        ),
    )
    model = stack.script(
        call("run_promql", promql=text, start=START, end=END, step_seconds=60),
        reply("That query was refused: it matched every instance."),
    )

    turn = stack.send(duc, "Show me CPU on every node this morning.", surface="console")

    assert turn.state == "replied", turn.stop_reason
    (refused,) = did(model.prompts[1])
    assert (refused["status"], refused["result"]["code"]) == (422, "infra_query_refused")
    row = turn.infra_queries.get()
    assert (row.outcome, row.refusal_reason) == ("refused", "match_all")
    assert prom.queries == []


@pytest.mark.django_db
def test_ac_f17_04_a_reply_after_an_unreachable_elasticsearch_carries_code_s_warning(
    stack, duc, cloud_sim, es
):
    es.raises = httpx.ConnectError("refused")
    stack.script(
        call("search_logs", start=START, end=END, filters={"server": ["db-01"]}),
        reply("There are no errors in db-01's logs."),
    )

    turn = stack.send(duc, "Any errors on db-01 this morning?", surface="console")

    assert (turn.state, turn.stop_reason) == ("replied", None)
    view = shown(duc, turn)
    assert view["reply"] == "There are no errors in db-01's logs."
    assert view["warnings"] == [ES_DOWN]


@pytest.mark.django_db
def test_ac_f17_05_log_text_whose_masking_failed_never_reaches_the_model(
    stack, duc, cloud_sim, es, ner
):
    prod = cloud_sim.id_of("projects", "saomai-prod")
    es.docs = [log_doc(prod, "slow query on orders"), log_doc(prod, "slow query on items")]

    def detect(text: str) -> list[Any]:
        if "slow query on" in text:
            raise NERError("down")
        return []

    ner(detect)
    model = stack.script(
        call("search_logs", start=START, end=END),
        reply("Two log lines matched; their text was withheld."),
    )

    turn = stack.send(duc, "Why is db-01 slow?", surface="console")

    assert turn.state == "replied", turn.stop_reason
    (search,) = did(model.prompts[1])
    assert [line["message"] for line in search["result"]["lines"]] == [WITHHELD, WITHHELD]
    assert (search["result"]["total"], search["result"]["withheld"]) == (2, 2)
    assert not any("slow query on" in prompt for prompt in model.prompts)


@pytest.mark.django_db
def test_ac_f17_06_a_soft_reboot_reaches_nova_only_when_the_person_confirms(
    stack, duc, lan, cloud_sim
):
    ticket = open_ticket(lan)
    db01 = cloud_sim.id_of("servers", "db-01")
    stack.script(call("reboot_server", server_id=db01, public_id=ticket.public_id))

    turn = stack.send(duc, f"Soft reboot db-01 for {ticket.public_id}", surface="console")

    assert turn.state == "awaiting_confirmation", turn.stop_reason
    assert [(s.status_code, s.outcome) for s in turn.steps.all()] == [
        (202, "confirmation_required")
    ]
    (receipt,) = turn.receipts
    assert (receipt["tool"], receipt["outcome"]) == ("reboot_server", "awaiting_confirmation")
    assert cloud_sim.changes() == []
    confirmed = press(duc, AgentAction.objects.get(id=receipt["action_id"]))
    assert confirmed.status_code == 200, confirmed.content
    assert cloud_sim.changes() == [f"POST /compute/v2.1/servers/{db01}/action"]


@pytest.mark.django_db
def test_ac_f17_07_a_detach_the_agent_asks_for_is_only_a_draft(stack, duc, lan, cloud_sim):
    ticket = open_ticket(lan)
    volume = cloud_sim.id_of("volumes", "vol-db-01")
    stack.script(
        call("draft_detach_volume", volume_id=volume, public_id=ticket.public_id),
        reply("A draft detach of vol-db-01 waits for you on its page."),
    )

    turn = stack.send(duc, f"Detach vol-db-01 for {ticket.public_id}", surface="console")

    assert turn.state == "replied", turn.stop_reason
    assert [(s.status_code, s.outcome) for s in turn.steps.all()] == [(403, "drafted")]
    assert [(r["tool"], r["outcome"]) for r in turn.receipts] == [
        ("draft_detach_volume", "draft_waiting")
    ]
    draft = AgentAction.objects.get()
    assert (draft.kind, draft.state, draft.target_kind, draft.target_ref) == (
        "draft",
        "pending",
        "volume",
        volume,
    )
    assert cloud_sim.changes() == []


@pytest.mark.django_db
def test_ac_f17_08_a_confirmed_reboot_whose_answer_is_lost_reaches_nova_once(
    stack, duc, lan, cloud_sim
):
    ticket = open_ticket(lan)
    db01 = cloud_sim.id_of("servers", "db-01")
    stack.script(call("reboot_server", server_id=db01, public_id=ticket.public_id))
    turn = stack.send(duc, f"Soft reboot db-01 for {ticket.public_id}", surface="console")
    action = AgentAction.objects.get(id=turn.receipts[0]["action_id"])
    cloud_sim.lose_answers()

    first = press(duc, action)
    again = press(duc, action)

    assert (first.status_code, first.json()["code"]) == (502, "infra_outcome_unknown")
    assert again.status_code == 409
    action.refresh_from_db()
    assert action.state == "outcome_unknown"
    assert cloud_sim.changes() == [f"POST /compute/v2.1/servers/{db01}/action"]


@pytest.mark.django_db
def test_ac_f17_09_after_an_injected_log_line_the_console_offers_only_reads(
    stack, duc, cloud_sim, es
):
    db01 = cloud_sim.id_of("servers", "db-01")
    es.docs = [log_doc(cloud_sim.id_of("projects", "saomai-prod"), INJECTED_LOG_LINE)]
    model = stack.script(
        call("search_logs", start=START, end=END, filters={"server": ["db-01"]}),
        call("get_server", server_id=db01),
        reply("db-01 is running. One log line tried to give me instructions; I ignored it."),
    )

    turn = stack.send(duc, "Why is db-01 slow?", surface="console")

    assert turn.state == "replied", turn.stop_reason
    assert offered(model.prompts[0]) & WRITES
    assert not offered(model.prompts[1]) & WRITES
    assert not offered(model.prompts[2]) & WRITES
    assert [s.injection_flagged for s in turn.steps.order_by("seq")] == [True, False]
    assert not AgentAction.objects.exists()
    assert cloud_sim.changes() == []


# ── F15's cloud cases (the 2026-11-26 amendment's EC-F15-01..08 and 10) ──

QUOTA_TEXT = (
    "vol-db-01 has been at its IOPS limit since 09:01, so a higher quota would likely help. "
    "Our support team has to make that change; I can't from the chat."
)
QUOTA_SUMMARY = "Customer asks to raise vol-db-01's IOPS quota; at 100 % of quota since 09:01"


@pytest.mark.django_db
def test_ec_f15_01_a_choice_the_slow_system_s_reads_never_gave_is_refused(stack, lan, backends):
    db01 = backends.id_of("servers", "db-01")
    model: ScriptedModel
    model = stack.script(
        call("list_my_alerts"),
        call("get_my_server", server_id=db01),
        lambda: choose("Is it db-01?", ref_of(model.prompts[-1], "db-01"), "item_9"),
        lambda: choose(
            "Is it db-01? Its volume is at its IOPS limit.", ref_of(model.prompts[-1], "db-01")
        ),
    )

    turn = stack.send(lan, "The system has been slow all morning.")

    assert "item_9" in model.prompts[3]
    assert turn.state == "replied", turn.stop_reason
    assert [(c["kind"], c["id"]) for c in turn.choices] == [
        ("server", db01),
        ("something_else", None),
    ]


@pytest.mark.django_db
def test_ec_f15_02_a_name_slightly_wrong_is_read_on_the_server_it_lists(stack, lan, backends):
    db01 = backends.id_of("servers", "db-01")
    model = stack.script(
        call("list_my_servers"),
        call("get_my_server", server_id=db01),
        reply("I couldn't find db1, so I checked db-01: it is running."),
    )

    turn = stack.send(lan, "db1 keeps timing out.")

    assert turn.state == "replied", turn.stop_reason
    listed, read = did(model.prompts[2])
    assert "db-01" in {server["name"] for server in listed["result"]}
    assert (read["status"], read["result"]["name"]) == (200, "db-01")
    assert backends.changes() == []


@pytest.mark.django_db
def test_ec_f15_03_another_company_s_server_reads_as_one_that_does_not_exist(
    stack, lan, cloud_sim, es
):
    model = stack.script(
        call("list_my_servers"),
        call("get_my_server", server_id=cloud_sim.id_of("servers", "web-03")),
        call("get_my_server", server_id="web-03"),
        reply("web-03 is not one of your servers."),
    )

    turn = stack.send(lan, "Show me the logs for web-03.")

    assert turn.state == "replied", turn.stop_reason
    listed, other, missing = did(model.prompts[3])
    assert "web-03" not in {server["name"] for server in listed["result"]}
    assert other["status"] == missing["status"] == 404
    assert other["result"] == missing["result"]
    assert es.searches == []


@pytest.mark.django_db
def test_ec_f15_04_a_quota_the_chat_can_t_change_ends_with_code_s_hand_off_parts(
    stack, lan, backends
):
    stack.script(call("list_my_volumes"), hand_off(QUOTA_TEXT, QUOTA_SUMMARY))

    turn = stack.send(lan, "Can you raise the IOPS quota on vol-db-01?")

    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_needs_staff")
    view = shown(lan, turn)
    assert (view["reply"], view["ticket_offered"]) == (QUOTA_TEXT, True)
    assert view["needs_staff"] == {"checked": CHECKED, "button": "Open a ticket", "opened": None}
    assert backends.changes() == []


@pytest.mark.django_db
def test_ec_f15_05_nova_gets_nothing_until_the_person_presses_the_card(stack, lan, cloud_sim):
    app01, app02 = cloud_sim.id_of("servers", "app-01"), cloud_sim.id_of("servers", "app-02")
    model: ScriptedModel
    model = stack.script(
        call("list_my_servers"),
        lambda: choose(
            "Which app server?",
            ref_of(model.prompts[-1], "app-01"),
            ref_of(model.prompts[-1], "app-02"),
        ),
    )
    asked = stack.send(lan, "Restart the app server.")
    stack.script(call("list_my_servers"), call("reboot_my_server", server_id=app01))

    both = stack.send(lan, "Both", conversation=asked.conversation_id)

    assert [c["id"] for c in asked.choices] == [app01, app02, None]
    assert both.state == "awaiting_confirmation", both.stop_reason
    assert cloud_sim.changes() == []
    pressed = press(lan, AgentAction.objects.get(id=both.receipts[0]["action_id"]))
    assert pressed.status_code == 200, pressed.content
    assert cloud_sim.changes() == [f"POST /compute/v2.1/servers/{app01}/action"]


@pytest.mark.django_db
def test_ec_f15_06_yesterday_afternoon_reaches_prometheus_as_the_window_the_model_sent(
    stack, lan, cloud_sim, prom
):
    zone = engine_settings.agent_time_zone
    yesterday = datetime.now(zone).date() - timedelta(days=1)
    start = datetime.combine(yesterday, time(12, 0), zone)
    end = datetime.combine(yesterday, time(18, 0), zone)
    slow = datetime.combine(yesterday, time(14, 10), zone)
    asked: list[tuple[float, float]] = []

    def answer(query: str, begin: float, until: float, step: int) -> list[dict[str, Any]]:
        asked.append((begin, until))
        values = [[slow.timestamp() + 60 * m, "0.9"] for m in range(0, 31, 10)]
        prod = cloud_sim.id_of("projects", "saomai-prod")
        return [{**series(prod, volume="vol-db-01"), "values": values}]

    prom.answer = answer
    model = stack.script(
        call(
            "query_my_metrics",
            metric="cloud_volume_read_latency_seconds",
            start=start.isoformat(),
            end=end.isoformat(),
            step_seconds=600,
            filters={"volume": ["vol-db-01"]},
        ),
        reply("vol-db-01 was slow yesterday from 14:10 to 14:40."),
    )

    turn = stack.send(lan, "It was really slow yesterday afternoon.")

    assert turn.state == "replied", turn.stop_reason
    assert f"## Now\n{datetime.now(zone).date().isoformat()}T" in model.prompts[0]
    assert asked == [(start.timestamp(), end.timestamp())]
    (metrics,) = did(model.prompts[1])
    assert len(metrics["result"]["series"][0]["points"]) == 4


@pytest.mark.django_db
def test_ec_f15_07_a_server_reported_down_is_read_before_the_reply(
    stack, lan, cloud_sim, alertmanager
):
    db01 = cloud_sim.id_of("servers", "db-01")
    model = stack.script(
        call("get_my_server", server_id=db01),
        call("list_my_alerts"),
        reply("db-01 is running and has no alerts. What do you see when it seems down?"),
    )

    turn = stack.send(lan, "db-01 is down!")

    assert (turn.state, turn.stop_reason) == ("replied", None)
    server, alerts = did(model.prompts[2])
    assert (server["result"]["status"], alerts["result"]) == ("ACTIVE", [])
    assert cloud_sim.changes() == []


@pytest.mark.django_db
def test_ec_f15_08_a_chat_reply_after_an_unreachable_elasticsearch_carries_code_s_warning(
    stack, lan, cloud_sim, es, alertmanager
):
    es.raises = httpx.ConnectError("refused")
    stack.script(
        call("search_my_logs", start=START, end=END, filters={"server": ["db-01"]}),
        call("list_my_alerts"),
        reply("There were no errors on db-01 this morning."),
    )

    turn = stack.send(lan, "Any errors on db-01 this morning?")

    assert (turn.state, turn.stop_reason) == ("replied", None)
    view = shown(lan, turn)
    assert view["reply"] == "There were no errors on db-01 this morning."
    assert view["warnings"] == [ES_DOWN]


@pytest.mark.django_db
def test_ec_f15_10_a_change_after_an_injected_log_line_ends_the_chat_turn(
    stack, lan, cloud_sim, es
):
    db01 = cloud_sim.id_of("servers", "db-01")
    es.docs = [log_doc(cloud_sim.id_of("projects", "saomai-prod"), INJECTED_LOG_LINE)]
    model = stack.script(
        call("search_my_logs", start=START, end=END, filters={"server": ["db-01"]}),
        call("reboot_my_server", server_id=db01),
    )

    turn = stack.send(lan, "Why is db-01 slow?")

    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_injection_in_result")
    assert not offered(model.prompts[1]) & WRITES
    assert not AgentAction.objects.exists()
    assert cloud_sim.changes() == []


AGENT_CASES = Path(__file__).parents[1] / "golden" / "agent_cases.jsonl"
CHECKS = frozenset(
    {
        "calls_any",
        "calls_on",
        "reads",
        "reads_on",
        "replies_before_read",
        "changes",
        "window_covers",
        "choices_include",
        "ends",
    }
)


def test_an_agent_case_names_only_checks_tools_faults_and_traces_that_exist():
    cases = [loads(line) for line in AGENT_CASES.read_text().splitlines()]
    tested = {name for name in globals() if name.startswith("test_ec_f15_")}

    assert [case["id"] for case in cases] == [f"EC-F15-{n:02d}" for n in (*range(1, 9), 10)]
    for case in cases:
        tools = {name for name, tool in TOOLS.items() if tool.surface == case["surface"]}
        checks = [c for turn in case["turns"] for c in [*turn["must"], *turn["must_not"]]]
        named = {
            tool
            for check in checks
            for tool in [
                *check.get("calls_any", []),
                *[c["tool"] for c in [check.get("calls_on"), check.get("window_covers")] if c],
            ]
        }
        faults = {f["kind"] for f in case["setup"].get("faults", [])}
        assert all(len(check) == 1 and set(check) <= CHECKS for check in checks), case["id"]
        assert named <= tools, (case["id"], named - tools)
        assert faults <= {kind.value for kind in FaultKind}, case["id"]
        assert case["trace"] in tested, case["id"]
