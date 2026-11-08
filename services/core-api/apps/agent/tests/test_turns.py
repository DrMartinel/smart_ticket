"""
An agent turn in core-api (F15): a message is masked, stored and queued; the turn runs once
against ai-engine; what comes back is recorded, and every stop hands the turn to a person.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import RefreshSession
from apps.accounts.testing import agent_token_for
from apps.agent.models import (
    AgentAction,
    AgentConversation,
    AgentConversationEnd,
    AgentStep,
    AgentTurn,
    AgentTurnState,
)
from apps.agent.utils.actions import AGENT_ACTION_HEADER
from apps.agent.utils.turns import agent_turns
from apps.audit.models import AuditLog
from apps.core.testing import api_client_with
from apps.rollout.models import RolloutFlag
from apps.rollout.testing import all_live
from apps.security.models import SecurityAlert
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.utils.router import AGENT_HANDOFF_REASONS, ReasonCode

PHONE = "0912345678"


@pytest.fixture
def live(settings, db):
    all_live(settings)


@pytest.fixture
def queued(monkeypatch):
    """Stands in for the Celery tasks; tests run the turn themselves."""
    turns: list[str] = []
    tickets: list[str] = []

    class FakeRun:
        def delay(self, turn_id: str) -> None:
            turns.append(turn_id)

    class FakeProcess:
        def delay(self, ticket_id: str) -> None:
            tickets.append(ticket_id)

    monkeypatch.setattr("apps.agent.tasks.run_turn", FakeRun())
    monkeypatch.setattr("apps.tickets.tasks.process_ticket", FakeProcess())
    return turns


class Engine:
    """A stubbed ai-engine: NER finds nothing, and /v1/agent/turn answers `reply` or fails."""

    def __init__(self, serve_ai_engine) -> None:
        self.reply: dict[str, Any] | Exception = _replied("Done.")
        self.ner_fails = False
        self.turn_bodies: list[dict[str, Any]] = []
        self.calls = serve_ai_engine(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/pii/detect":
            if self.ner_fails:
                raise httpx.ConnectError("ner down")
            return httpx.Response(200, json={"spans": []})
        if request.url.path == "/v1/agent/turn":
            self.turn_bodies.append(json.loads(request.content))
            if isinstance(self.reply, Exception):
                raise self.reply
            return httpx.Response(200, json=self.reply)
        raise httpx.ConnectError(request.url.path)


@pytest.fixture
def engine(serve_ai_engine):
    return Engine(serve_ai_engine)


def _replied(text: str, steps: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "outcome": "replied",
        "reply": text,
        "steps": steps or [],
        "model": "deepseek-chat",
        "prompt_version": "agent.v1",
        "tokens_in": 1200,
        "tokens_out": 80,
        "cost_usd": 0.0012,
        **extra,
    }


def _handed_off(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        **_replied("partial model text"),
        "outcome": "handed_off",
        "stop_reason": reason,
        **extra,
    }


def _step(seq: int, method: str = "GET", outcome: str = "ok", **extra: Any) -> dict[str, Any]:
    return {
        "seq": seq,
        "tool": "my_tickets" if method == "GET" else "request_ticket",
        "arguments": {},
        "method": method,
        "path": "/api/requester/tickets"
        if method == "GET"
        else "/api/chat/tickets/T-1/create-ticket",
        "status_code": 200,
        "outcome": outcome,
        **extra,
    }


def _send(client: Client, message: str, surface: str = "chat", conversation: str | None = None):
    body: dict[str, Any] = {"message": message, "surface": surface}
    if conversation:
        body["conversation_id"] = conversation
    return client.post("/api/agent/turns", body, content_type="application/json")


def _start(client: Client, message: str = "My VPN drops every ten minutes.", **kw) -> AgentTurn:
    response = _send(client, message, **kw)
    assert response.status_code == 202, response.content
    return AgentTurn.objects.get(id=response.json()["turn_id"])


def _ticket(turn: AgentTurn) -> Ticket:
    assert turn.handoff_ticket is not None
    return turn.handoff_ticket


# ── starting a turn ──


@pytest.mark.django_db
def test_a_message_whose_masking_failed_reaches_no_model_and_hands_off(
    employee_user, api_as, live, engine, queued
):
    engine.ner_fails = True

    turn = _start(api_as(employee_user), f"Call me on {PHONE}, my VPN is down")

    turn.refresh_from_db()
    assert engine.turn_bodies == [] and queued == []
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_mask_failed")
    assert PHONE not in turn.message_masked
    conversation = turn.conversation
    assert (conversation.state, conversation.end_reason) == ("ended", "mask_failed")
    ticket = _ticket(turn)
    assert ticket is not None
    assert (ticket.pii_level, ticket.agent_handoff_reason) == ("mask_failed", "agent_mask_failed")
    assert ticket.agent_turn_id == turn.id


@pytest.mark.django_db
def test_a_message_with_critical_pii_reaches_no_model_and_hands_off(
    employee_user, api_as, live, engine, queued
):
    turn = _start(api_as(employee_user), "My VPN fails, password: hunter2xyz")

    turn.refresh_from_db()
    assert engine.turn_bodies == [] and queued == []
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_pii_critical")
    assert "hunter2xyz" not in turn.message_masked
    ticket = _ticket(turn)
    assert (ticket.pii_level, ticket.agent_handoff_reason) == ("critical", "agent_pii_critical")


@pytest.mark.django_db
def test_a_console_message_with_critical_pii_raises_a_security_alert(
    technician_user, api_as, live, engine, queued
):
    turn = _start(api_as(technician_user), "token: abc123secret", surface="console")

    turn.refresh_from_db()
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_pii_critical")
    assert engine.turn_bodies == []
    alert = SecurityAlert.objects.get()
    assert (alert.kind, alert.subject_user_id) == ("pii_critical", technician_user.id)


@pytest.mark.django_db
def test_placeholders_number_on_across_a_conversation_s_turns(
    employee_user, api_as, live, engine, queued
):
    client = api_as(employee_user)
    first = _start(client, f"Call me on {PHONE}")
    agent_turns.run(first.id)

    second = _start(client, "Or on 0987654321", conversation=str(first.conversation_id))

    first.refresh_from_db()
    assert first.pii_map.keys().isdisjoint(second.pii_map.keys())
    assert len(AgentTurn.objects.pii_map_of(first.conversation_id)) == 2


@pytest.mark.django_db
def test_the_agent_is_off_while_its_flag_is_off(employee_user, api_as, settings, engine, queued):
    all_live(settings)
    RolloutFlag.objects.filter(branch="agent_chat").update(state="off")

    response = _send(api_as(employee_user), "Hello")

    assert (response.status_code, response.json()["code"]) == (403, "agent_off")
    assert not AgentTurn.objects.exists()


@pytest.mark.django_db
def test_the_agent_is_off_in_shadow_mode(employee_user, api_as, settings, engine, queued):
    all_live(settings)
    settings.SHADOW_MODE = True

    assert _send(api_as(employee_user), "Hello").json()["code"] == "agent_off"


@pytest.mark.django_db
def test_the_console_agent_needs_ticket_read(employee_user, api_as, live, engine, queued):
    response = _send(api_as(employee_user), "Hello", surface="console")

    assert (response.status_code, response.json()["code"]) == (403, "permission_missing")
    assert not AgentTurn.objects.exists()


@pytest.mark.django_db
def test_a_second_message_while_a_turn_is_unfinished_is_refused(
    employee_user, api_as, live, engine, queued
):
    client = api_as(employee_user)
    first = _start(client)

    response = _send(client, "And another thing", conversation=str(first.conversation_id))

    assert (response.status_code, response.json()["code"]) == (409, "turn_running")


@pytest.mark.django_db
def test_an_ended_conversation_takes_no_message(employee_user, api_as, live, engine, queued):
    client = api_as(employee_user)
    first = _start(client)
    agent_turns.run(first.id)
    client.post(f"/api/agent/conversations/{first.conversation_id}/end")

    response = _send(client, "Hello again", conversation=str(first.conversation_id))

    assert (response.status_code, response.json()["code"]) == (409, "conversation_ended")


@pytest.mark.django_db
def test_an_idle_conversation_ends_when_it_is_next_used(
    employee_user, api_as, live, engine, queued, settings
):
    client = api_as(employee_user)
    first = _start(client)
    agent_turns.run(first.id)
    idle = settings.THRESHOLDS.agent.conversation_idle_minutes
    AgentConversation.objects.filter(id=first.conversation_id).update(
        last_activity_at=timezone.now() - timedelta(minutes=idle + 1)
    )

    response = _send(client, "Hello again", conversation=str(first.conversation_id))

    assert response.json()["code"] == "conversation_ended"
    assert AgentConversation.objects.get(id=first.conversation_id).end_reason == "idle"


@pytest.mark.django_db
def test_someone_elses_conversation_is_not_found(
    employee_user, technician_user, api_as, live, engine, queued
):
    theirs = _start(api_as(technician_user))

    response = _send(api_as(employee_user), "Hello", conversation=str(theirs.conversation_id))

    assert response.status_code == 404


@pytest.mark.django_db
def test_a_message_is_stored_masked_with_its_quarantine_and_queued(
    employee_user, api_as, live, engine, queued, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        turn = _start(api_as(employee_user), f"Call me on {PHONE}, my VPN is down")

    assert PHONE not in turn.message_masked
    assert (turn.state, turn.seq) == ("queued", 1)
    assert queued == [str(turn.id)]
    (placeholder,) = turn.pii_map
    assert placeholder in turn.message_masked
    assert PiiQuarantine.objects.filter(agent_turn=turn, ticket=None).count() == 1


# ── running a turn ──


@pytest.mark.django_db
def test_an_unreachable_ai_engine_hands_off_as_a_chat_ticket(
    employee_user, api_as, live, engine, queued
):
    engine.reply = httpx.ConnectError("down")
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_engine_unavailable")
    assert _ticket(turn).agent_handoff_reason == "agent_engine_unavailable"
    assert _ticket(turn).body_masked == turn.message_masked


@pytest.mark.django_db
def test_a_short_message_s_hand_off_opens_a_ticket(employee_user, api_as, live, engine, queued):
    engine.reply = httpx.ConnectError("down")
    turn = _start(api_as(employee_user), "help")

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    ticket = _ticket(turn)
    assert (ticket.subject_masked, ticket.body_masked) == ("help", "help")


@pytest.mark.django_db
def test_a_hand_off_whose_ticket_fails_leaves_the_turn_running(
    employee_user, api_as, live, engine, queued, monkeypatch
):
    engine.reply = httpx.ConnectError("down")
    turn = _start(api_as(employee_user))

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("apps.agent.utils.turns.ticket_intake.open_for_agent", fail)
    with pytest.raises(RuntimeError):
        agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.handoff_ticket_id) == ("running", None)
    assert not AuditLog.objects.filter(event="agent_turn_handed_off").exists()


@pytest.mark.django_db
def test_a_console_hand_off_opens_no_ticket(technician_user, api_as, live, engine, queued):
    engine.reply = _handed_off("tool_failed")
    turn = _start(api_as(technician_user), surface="console")

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.stop_reason, turn.handoff_ticket) == (
        "handed_off",
        "agent_tool_failed",
        None,
    )
    assert not Ticket.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stop", "reason"),
    [
        ("step_limit", "agent_step_limit"),
        ("tool_limit", "agent_tool_limit"),
        ("budget", "agent_budget_exceeded"),
        ("tool_failed", "agent_tool_failed"),
        ("tool_outcome_unknown", "agent_tool_outcome_unknown"),
        ("injection", "agent_injection_detected"),
        ("injection_in_result", "agent_injection_in_result"),
        ("model_unavailable", "agent_model_unavailable"),
        ("schema_invalid", "agent_schema_invalid"),
    ],
)
def test_each_stop_hands_off_with_its_reason_and_drops_the_models_text(
    employee_user, api_as, live, engine, queued, stop, reason
):
    engine.reply = _handed_off(stop)
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.stop_reason) == ("handed_off", reason)
    assert "partial model text" not in turn.reply_text and turn.reply_text
    assert _ticket(turn).agent_handoff_reason == reason


@pytest.mark.django_db
def test_a_hand_off_without_a_stop_reason_is_schema_invalid(
    employee_user, api_as, live, engine, queued
):
    engine.reply = _handed_off("step_limit", stop_reason=None)
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert turn.stop_reason == "agent_schema_invalid"


@pytest.mark.django_db
def test_a_refused_token_ends_the_turn_without_a_ticket(
    employee_user, api_as, live, engine, queued
):
    engine.reply = _handed_off("token_refused")
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.stop_reason, turn.handoff_ticket) == ("agent_token_refused", None)
    assert not Ticket.objects.exists()


@pytest.mark.django_db
def test_a_signed_out_user_s_turn_never_reaches_ai_engine(
    employee_user, api_as, live, engine, queued
):
    turn = _start(api_as(employee_user))
    RefreshSession.objects.filter(user=employee_user).update(revoked_at=timezone.now())

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert engine.turn_bodies == []
    assert (turn.stop_reason, turn.handoff_ticket) == ("agent_token_refused", None)


@pytest.mark.django_db
def test_an_injected_message_ends_the_conversation(employee_user, api_as, live, engine, queued):
    engine.reply = _handed_off("injection")
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    assert AgentConversation.objects.get(id=turn.conversation_id).end_reason == "injection"


@pytest.mark.django_db
def test_a_turn_runs_once_however_often_it_is_delivered(
    employee_user, api_as, live, engine, queued
):
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)
    agent_turns.run(turn.id)

    assert len(engine.turn_bodies) == 1


@pytest.mark.django_db
def test_a_late_answer_for_a_turn_already_handed_off_is_dropped(
    employee_user, api_as, live, engine, queued, monkeypatch
):
    turn = _start(api_as(employee_user))

    def answer_after_the_sweep(request):
        agent_turns._hand_off(turn.id, ReasonCode.AGENT_ENGINE_UNAVAILABLE)
        return _replied_response()

    def _replied_response():
        from infrastructure.dtos import AgentTurnResponse

        return AgentTurnResponse.model_validate(_replied("Too late", [_step(1, "POST")]))

    monkeypatch.setattr("apps.agent.utils.turns.ai_engine.agent_turn", answer_after_the_sweep)
    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.stop_reason) == ("handed_off", "agent_engine_unavailable")
    assert turn.reply_text != "Too late"
    assert not AgentStep.objects.exists()


@pytest.mark.django_db
def test_a_replied_turn_records_its_steps_receipts_and_usage(
    employee_user, api_as, live, engine, queued
):
    turn = _start(api_as(employee_user))
    engine.reply = _replied(
        "I opened it.", [_step(1, "GET"), _step(2, "POST"), _step(3, "POST", "refused")]
    )

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.reply_text, turn.tool_calls) == ("replied", "I opened it.", 3)
    assert (turn.model, turn.prompt_version, turn.tokens_in, turn.tokens_out) == (
        "deepseek-chat",
        "agent.v1",
        1200,
        80,
    )
    assert [r["outcome"] for r in turn.receipts] == ["done", "refused"]
    assert list(turn.steps.order_by("seq").values_list("outcome", flat=True)) == [
        "ok",
        "ok",
        "refused",
    ]


@pytest.mark.django_db
def test_a_write_whose_outcome_is_unknown_is_never_shown_as_failed(
    employee_user, api_as, live, engine, queued
):
    turn = _start(api_as(employee_user))
    engine.reply = _replied("Not sure it went through.", [_step(1, "POST", "unknown")])

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert [r["outcome"] for r in turn.receipts] == ["unknown"]


def test_the_frontends_may_send_the_agent_action_header(settings):
    response = Client().options(
        "/api/agent/actions",
        HTTP_ORIGIN=settings.CORS_ALLOWED_ORIGINS[0],
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=AGENT_ACTION_HEADER.lower(),
    )

    assert AGENT_ACTION_HEADER.lower() in response["access-control-allow-headers"]


@pytest.mark.django_db
def test_a_step_cannot_claim_an_action_of_another_turn(employee_user, api_as, live, engine, queued):
    other = _start(api_as(employee_user))
    agent_turns.run(other.id)
    action = AgentAction.objects.create(
        kind="confirm",
        user=employee_user,
        conversation=other.conversation,
        turn=other,
        method="POST",
        route="/api/x",
        path="/api/x",
        arguments={},
        arguments_sha256="0" * 64,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    turn = _start(api_as(employee_user))
    engine.reply = {
        **_replied("", [_step(1, "POST", "confirmation_required", action_id=str(action.id))]),
        "outcome": "awaiting_confirmation",
    }

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    assert turn.state == "awaiting_confirmation"
    assert turn.steps.get().action_id is None
    assert turn.receipts[0]["action_id"] is None


@pytest.mark.django_db
def test_ai_engine_gets_the_limits_language_and_no_access(
    employee_user, api_as, live, engine, queued, settings
):
    employee_user.language = "en"
    employee_user.save(update_fields=["language"])
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    (body,) = engine.turn_bodies
    th = settings.THRESHOLDS.agent
    assert body["limits"] == {
        "max_steps": th.max_steps,
        "max_tool_calls": th.max_tool_calls_per_turn,
        "max_model_tokens": th.max_model_tokens_per_turn,
    }
    assert (body["surface"], body["language"], body["message_masked"]) == (
        "chat",
        "en",
        turn.message_masked,
    )
    assert body["token"] and "permission" not in json.dumps(body)


@pytest.mark.django_db
def test_earlier_turns_are_capped_oldest_first_and_never_unmasked(
    employee_user, api_as, live, engine, queued, settings
):
    settings.THRESHOLDS.agent.max_earlier_turns = 2
    client = api_as(employee_user)
    first = _start(client, "first message")
    agent_turns.run(first.id)
    for text in ("second message", "third message"):
        agent_turns.run(_start(client, text, conversation=str(first.conversation_id)).id)
    AgentTurn.objects.filter(conversation_id=first.conversation_id, seq=3).update(
        pii_level="mask_failed"
    )
    fourth = _start(client, "fourth message", conversation=str(first.conversation_id))

    earlier = agent_turns.earlier_turns(fourth)

    assert [t.message_masked for t in earlier] == ["first message", "second message"]


# ── what a hand-off ticket carries (BR-F15-14, BR-F15-18) ──


@pytest.mark.django_db
def test_a_hand_off_ticket_carries_the_turns_quarantine_entries(
    employee_user, api_as, live, engine, queued
):
    engine.reply = _handed_off("step_limit")
    turn = _start(api_as(employee_user), f"Call me on {PHONE}, my VPN is down")

    agent_turns.run(turn.id)

    turn.refresh_from_db()
    ticket = _ticket(turn)
    (placeholder,) = ticket.pii_map
    assert placeholder in ticket.body_masked
    copy = PiiQuarantine.objects.get(ref=ticket.pii_map[placeholder])
    original = PiiQuarantine.objects.get(ref=turn.pii_map[placeholder])
    assert (copy.ticket_id, copy.ciphertext) == (ticket.id, original.ciphertext)
    assert copy.ref != original.ref


@pytest.mark.django_db
def test_a_hand_off_ticket_is_audited_as_the_agent_s(employee_user, api_as, live, engine, queued):
    engine.reply = _handed_off("tool_failed")
    turn = _start(api_as(employee_user))

    agent_turns.run(turn.id)

    submitted = AuditLog.objects.get(event="ticket_submitted")
    assert submitted.payload["via"] == "agent"
    assert submitted.payload["agent_turn_id"] == str(turn.id)
    handed = AuditLog.objects.get(event="agent_turn_handed_off")
    assert handed.payload["reason"] == "agent_tool_failed"


def test_every_hand_off_reason_has_a_message_in_both_languages():
    from apps.agent.utils.vocabulary import HANDOFF_TEXT

    assert set(HANDOFF_TEXT) == AGENT_HANDOFF_REASONS | {ReasonCode.AGENT_TOKEN_REFUSED}
    assert all(set(texts) == {"vi", "en"} for texts in HANDOFF_TEXT.values())


def test_every_stop_reason_maps_to_an_agent_reason_code():
    from apps.agent.utils.vocabulary import STOP_REASONS
    from infrastructure.dtos import AgentStopReason

    assert set(STOP_REASONS) == set(AgentStopReason)
    assert set(STOP_REASONS.values()) <= AGENT_HANDOFF_REASONS | {ReasonCode.AGENT_TOKEN_REFUSED}


# ── the agent token (FR-F15-003, FR-F15-015) ──


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["queued", "replied", "handed_off"])
def test_a_token_of_a_turn_that_is_not_running_is_refused(employee_user, state):
    token = agent_token_for(employee_user)
    AgentTurn.objects.update(state=state)

    assert api_client_with(token).get("/api/requester/tickets").status_code == 401


@pytest.mark.django_db
def test_a_token_of_an_ended_conversation_is_refused(employee_user):
    token = agent_token_for(employee_user)
    AgentConversation.objects.update(state="ended", end_reason=AgentConversationEnd.USER.value)

    assert api_client_with(token).get("/api/requester/tickets").status_code == 401


@pytest.mark.django_db
def test_a_token_naming_someone_else_s_turn_is_refused(employee_user, technician_user):
    turn = AgentTurn.objects.get(id=uuid.UUID(_turn_of(agent_token_for(technician_user))))
    token = agent_token_for(employee_user, turn=turn.id)

    assert api_client_with(token).get("/api/requester/tickets").status_code == 401


def _turn_of(token: str) -> str:
    from ninja_jwt.tokens import AccessToken

    return str(AccessToken(token)["agt"])


@pytest.mark.django_db
def test_a_turn_s_writes_beyond_the_cap_are_refused(employee_user, settings, live, engine, queued):
    settings.THRESHOLDS.agent.max_tool_calls_per_turn = 1
    token = agent_token_for(employee_user)
    client = api_client_with(token)
    client.defaults["HTTP_X_AGENT_TOOL"] = "ask_helpdesk"

    for _ in range(3):
        assert client.get("/api/requester/tickets").status_code == 200
    first = client.post(
        "/api/chat/ask", {"message": "VPN drops every ten minutes"}, content_type="application/json"
    )
    second = client.post(
        "/api/chat/ask", {"message": "VPN drops every ten minutes"}, content_type="application/json"
    )

    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (429, "agent_tool_limit")
    assert AgentTurn.objects.get().write_calls == 1


# ── agent.sweep (FR-F15-019) ──


@pytest.mark.django_db
def test_the_sweep_hands_off_turns_stuck_running_or_queued(
    employee_user, api_as, live, engine, queued, settings
):
    client = api_as(employee_user)
    stale = timezone.now() - timedelta(seconds=settings.THRESHOLDS.agent.token_ttl_seconds + 1)
    running = _start(client)
    AgentTurn.objects.filter(id=running.id).update(state="running", started_at=stale)
    waiting = _start(api_as(employee_user))
    AgentTurn.objects.filter(id=waiting.id).update(queued_at=stale)
    fresh = _start(api_as(employee_user))

    result = agent_turns.sweep()

    assert result.turns_failed == 2
    states = dict(AgentTurn.objects.values_list("id", "stop_reason"))
    assert states[running.id] == states[waiting.id] == "agent_engine_unavailable"
    assert AgentTurn.objects.get(id=fresh.id).state == AgentTurnState.QUEUED.value


@pytest.mark.django_db
def test_the_sweep_expires_actions_and_ends_idle_conversations(
    employee_user, api_as, live, engine, queued, settings
):
    turn = _start(api_as(employee_user))
    agent_turns.run(turn.id)
    action = AgentAction.objects.create(
        kind="draft",
        user=employee_user,
        conversation=turn.conversation,
        turn=turn,
        method="POST",
        route="/api/x",
        path="/api/x",
        arguments={},
        arguments_sha256="0" * 64,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    idle = settings.THRESHOLDS.agent.conversation_idle_minutes
    AgentConversation.objects.update(last_activity_at=timezone.now() - timedelta(minutes=idle + 1))

    result = agent_turns.sweep()

    assert (result.actions_expired, result.conversations_ended) == (1, 1)
    action.refresh_from_db()
    assert action.state == "expired"
    assert AgentConversation.objects.get().end_reason == "idle"


# ── the routes (§h.2) ──


@pytest.mark.django_db
def test_someone_else_s_turn_is_not_found(
    employee_user, technician_user, api_as, live, engine, queued
):
    theirs = _start(api_as(technician_user))

    assert api_as(employee_user).get(f"/api/agent/turns/{theirs.id}").status_code == 404


@pytest.mark.django_db
def test_a_turn_reads_back_with_its_reply_and_hand_off_ticket(
    employee_user, api_as, live, engine, queued
):
    engine.reply = _handed_off("budget")
    client = api_as(employee_user)
    turn = _start(client)
    agent_turns.run(turn.id)

    body = client.get(f"/api/agent/turns/{turn.id}").json()
    conversation = client.get(f"/api/agent/conversations/{turn.conversation_id}").json()

    turn.refresh_from_db()
    assert body["state"] == "handed_off"
    assert body["stop_reason"] == "agent_budget_exceeded"
    assert body["handoff_ticket"] == _ticket(turn).public_id
    assert [t["turn_id"] for t in conversation["turns"]] == [str(turn.id)]


@pytest.mark.django_db
def test_an_action_is_dismissed_once(employee_user, technician_user, api_as, live, engine, queued):
    turn = _start(api_as(employee_user))
    action = AgentAction.objects.create(
        kind="confirm",
        user=employee_user,
        conversation=turn.conversation,
        turn=turn,
        method="POST",
        route="/api/x",
        path="/api/tickets/T-1/take",
        arguments={},
        arguments_sha256="0" * 64,
        target_kind="ticket",
        target_ref="T-1",
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    client = api_as(employee_user)

    listed = client.get("/api/agent/actions?state=pending&ticket=T-1").json()
    not_theirs = api_as(technician_user).post(f"/api/agent/actions/{action.id}/dismiss")
    first = client.post(f"/api/agent/actions/{action.id}/dismiss")
    second = client.post(f"/api/agent/actions/{action.id}/dismiss")

    assert [a["action_id"] for a in listed] == [str(action.id)]
    assert not_theirs.status_code == 404
    assert first.status_code == 204
    assert (second.status_code, second.json()["code"]) == (409, "not_pending")


@pytest.mark.django_db
def test_a_ticket_the_agent_asks_for_carries_the_turns_quarantine_entries(
    employee_user, api_as, live, engine, queued
):
    turn = _start(api_as(employee_user), f"Call me on {PHONE}, my VPN is down")
    AgentTurn.objects.filter(id=turn.id).update(state="running")
    (placeholder,) = turn.pii_map
    client = api_client_with(agent_token_for(employee_user, turn=turn.id))
    client.defaults["HTTP_X_AGENT_TOOL"] = "ask_helpdesk"

    response = client.post(
        "/api/chat/ask",
        {"message": f"VPN drops every ten minutes. Contact: {placeholder}"},
        content_type="application/json",
    )

    ticket = Ticket.objects.get(public_id=response.json()["public_id"])
    assert ticket.agent_turn_id == turn.id
    copy = PiiQuarantine.objects.get(ref=ticket.pii_map[placeholder])
    assert copy.ticket_id == ticket.id
    assert copy.ciphertext == PiiQuarantine.objects.get(ref=turn.pii_map[placeholder]).ciphertext
