"""Chat conversations and the earlier turns a question carries (F3, ADR-0034). What goes wrong
quietly here: another person's or another conversation's text reaching the model, a blocked turn
becoming context, or the context changing a routing decision."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.chat.models import Conversation
from apps.chat.utils.conversations import conversations
from apps.tickets.models import IncidentVerdict, RoutingDecision, Ticket
from apps.tickets.utils.masking import NERError
from apps.tickets.utils.pipeline import _degraded_signals, ticket_process
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import AIRunResponse, EngineSignals, TicketMasked

pytestmark = pytest.mark.django_db

FIRST = "VPN báo lỗi TLS handshake failed khi kết nối từ nhà"
SECOND = "Làm theo rồi vẫn lỗi, em dùng mạng 4G"


def response(request_id: str, *, injection: bool = False) -> AIRunResponse:
    """ai-engine with every check failed and nothing proposed; `injection` flags the ticket."""
    d = _degraded_signals()
    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="test",
        proposal=None,
        signals=EngineSignals(
            retrieval=d.retrieval,
            generation=d.generation,
            classification=d.classification,
            injection_detected=injection,
        ),
    )


@pytest.fixture
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@pytest.fixture
def enqueued(monkeypatch) -> list[str]:
    ids: list[str] = []

    class Fake:
        def delay(self, ticket_id: str) -> None:
            ids.append(ticket_id)

    monkeypatch.setattr("apps.tickets.tasks.process_ticket", Fake())
    return ids


@pytest.fixture
def engine(monkeypatch) -> dict[str, list]:
    """Records what reaches ai-engine; `flag` lists tickets it reports as injections."""
    sent: dict[str, list] = {"masked": [], "flag": []}
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(Ticket, "classify_similarity", lambda *a: IncidentVerdict(kind="unique"))

    def analyze(masked: TicketMasked, request_id: str) -> AIRunResponse:
        sent["masked"].append(masked)
        return response(request_id, injection=masked.ticket_public_id in sent["flag"])

    monkeypatch.setattr(ai_engine, "analyze", analyze)
    return sent


@pytest.fixture
def chat(employee_user, api_as, ner_finds_nothing, enqueued, engine, settings):
    """A live chat: questions are held for the requester, as outcomes like suggest_ticket need."""
    settings.SHADOW_MODE = False
    client = api_as(employee_user)

    def ask(message: str, conversation_id: str | None = None, *, run: bool = True):
        body = {"message": message}
        if conversation_id:
            body["conversation_id"] = conversation_id
        reply = client.post("/api/chat/ask", body, content_type="application/json")
        if run and reply.status_code == 200:
            ticket_process(enqueued[-1])
        return reply

    ask.client = client  # type: ignore[attr-defined]
    return ask


def idle(conversation_id: str, minutes: int) -> None:
    Conversation.objects.filter(id=conversation_id).update(
        last_activity_at=timezone.now() - timedelta(minutes=minutes)
    )


class TestPriorTurns:
    def test_follow_up_carries_same_conversation_context(self, chat, engine):
        """AC-F3-01."""
        first = chat(FIRST).json()
        second = chat(SECOND, first["conversation_id"]).json()

        assert second["conversation_id"] == first["conversation_id"]
        sent = engine["masked"][-1]
        assert [t.question_masked for t in sent.prior_turns] == [FIRST]
        assert sent.prior_turns[0].outcome == "suggest_ticket"

    def test_prior_turns_only_from_same_conversation_and_requester(
        self, chat, engine, technician_user
    ):
        """BR-F3-01: a turn another person put in the conversation is never context."""
        first = chat(FIRST).json()
        conversation = Conversation.objects.get(id=first["conversation_id"])
        stranger = Ticket.objects.create(
            public_id="TKT-OTHER-000001",
            reporter=technician_user,
            subject_masked="someone else's question",
            body_masked="someone else's question",
            pii_level="routine",
            conversation=conversation,
            status="pending_review",
        )
        RoutingDecision.objects.create(
            ticket=stranger,
            branch="hitl",
            reason_code="x",
            reason_detail="",
            thresholds_used={},
        )

        chat(SECOND, first["conversation_id"])

        assert [t.question_masked for t in engine["masked"][-1].prior_turns] == [FIRST]

    def test_no_context_across_conversations(self, chat, engine):
        """AC-F3-02: 35 minutes idle starts a new conversation with no prior turns."""
        first = chat(FIRST).json()
        idle(first["conversation_id"], 35)

        refused = chat(SECOND, first["conversation_id"])
        assert refused.status_code == 409
        assert refused.json()["code"] == "conversation_ended"

        second = chat(SECOND).json()
        assert second["conversation_id"] != first["conversation_id"]
        assert engine["masked"][-1].prior_turns == []
        assert Conversation.objects.get(id=first["conversation_id"]).end_reason == "idle"

    def test_blocked_turn_ends_conversation(self, chat, engine):
        """AC-F3-03 (BR-F3-02)."""
        first = chat(FIRST, run=False).json()
        engine["flag"].append(first["public_id"])
        ticket_process(str(Ticket.objects.get(public_id=first["public_id"]).id))
        assert RoutingDecision.objects.get(ticket__public_id=first["public_id"]).branch == "block"

        second = chat(SECOND).json()

        assert second["conversation_id"] != first["conversation_id"]
        assert engine["masked"][-1].prior_turns == []
        assert Conversation.objects.get(id=first["conversation_id"]).end_reason == "blocked"

    def test_a_blocked_turn_is_never_context_even_if_the_conversation_stayed_open(
        self, chat, engine
    ):
        first = chat(FIRST).json()
        decision = RoutingDecision.objects.get(ticket__public_id=first["public_id"])
        RoutingDecision.objects.filter(pk=decision.pk).update(branch="block")

        chat(SECOND, first["conversation_id"])

        assert engine["masked"][-1].prior_turns == []
        assert Conversation.objects.get(id=first["conversation_id"]).end_reason == "blocked"

    def test_a_mask_failed_turn_ends_the_conversation(self, chat, engine, monkeypatch):
        async def ner_down(*a, **kw):
            raise NERError("ner down")

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", ner_down)
        first = chat(FIRST, run=False).json()

        assert Conversation.objects.get(id=first["conversation_id"]).end_reason == "mask_failed"

    def test_an_undecided_turn_is_never_context(self, chat, engine):
        """A turn not yet past the injection check can't be context (ADR-0034)."""
        first = chat(FIRST, run=False).json()

        chat(SECOND, first["conversation_id"])

        assert engine["masked"][-1].prior_turns == []

    def test_at_most_max_prior_turns_most_recent_last(self, chat, engine, settings):
        conversation_id = None
        for n in range(8):
            reply = chat(f"Câu hỏi số {n} về VPN", conversation_id).json()
            conversation_id = reply["conversation_id"]

        sent = engine["masked"][-1].prior_turns
        assert len(sent) == settings.THRESHOLDS.requester.max_prior_turns
        assert [t.question_masked for t in sent] == [f"Câu hỏi số {n} về VPN" for n in range(1, 7)]

    def test_a_failure_building_context_analyses_the_ticket_alone(self, chat, engine, monkeypatch):
        """ADR-0034: degrade toward the old behaviour and end the conversation."""
        first = chat(FIRST).json()

        def broken(ticket):
            raise RuntimeError("db hiccup")

        monkeypatch.setattr(conversations, "prior_turns", broken)
        second = chat(SECOND, first["conversation_id"]).json()

        assert engine["masked"][-1].prior_turns == []
        assert Conversation.objects.get(id=first["conversation_id"]).end_reason == "context_failed"
        assert AuditLog.objects.filter(event="prior_turns_failed").count() == 1
        assert RoutingDecision.objects.filter(ticket__public_id=second["public_id"]).exists()


class TestRouterIgnoresPriorTurns:
    def test_router_ignores_prior_turns(self, chat, engine):
        """AC-F3-04 (BR-F3-03): same signals, same branch and reason, with and without context."""
        first = chat(FIRST).json()
        with_context = chat(SECOND, first["conversation_id"]).json()
        idle(first["conversation_id"], 35)
        alone = chat(SECOND).json()

        assert engine["masked"][-2].prior_turns != []
        assert engine["masked"][-1].prior_turns == []
        decided = {
            d.ticket.public_id: (d.branch, d.reason_code)
            for d in RoutingDecision.objects.select_related("ticket")
        }
        assert decided[with_context["public_id"]] == decided[alone["public_id"]]


class TestConversationEndpoints:
    def test_new_conversation_ends_the_current_one(self, chat):
        first = chat(FIRST).json()

        ended = chat.client.post(f"/api/chat/conversations/{first['conversation_id']}/end")

        assert ended.status_code == 204
        assert chat(SECOND, first["conversation_id"]).status_code == 409
        assert Conversation.objects.get(id=first["conversation_id"]).end_reason == "user"

    def test_another_persons_conversation_is_not_found(self, chat, technician_user, api_as):
        first = chat(FIRST).json()

        other = api_as(technician_user)
        assert (
            other.post(f"/api/chat/conversations/{first['conversation_id']}/end").status_code == 404
        )
        refused = other.post(
            "/api/chat/ask",
            {"message": SECOND, "conversation_id": first["conversation_id"]},
            content_type="application/json",
        )
        assert refused.status_code == 404

    def test_the_chat_shows_only_the_current_conversation(self, chat):
        """FR-F3-004."""
        first = chat(FIRST).json()
        idle(first["conversation_id"], 35)

        assert chat.client.get("/api/chat/tickets").json() == []
        second = chat(SECOND).json()
        shown = chat.client.get("/api/chat/tickets").json()
        assert [t["public_id"] for t in shown] == [second["public_id"]]
        older = chat.client.get(
            "/api/chat/tickets", {"conversation_id": first["conversation_id"]}
        ).json()
        assert [t["public_id"] for t in older] == [first["public_id"]]

    def test_the_sweep_ends_idle_conversations(self, chat):
        first = chat(FIRST).json()
        idle(first["conversation_id"], 31)

        assert conversations.end_idle() == 1
        assert conversations.end_idle() == 0
