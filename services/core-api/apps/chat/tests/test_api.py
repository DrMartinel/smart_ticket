"""
The requester's chat over HTTP. What can go wrong quietly here: one
requester reading another's conversation, an answer shown that the router
never allowed, or "create ticket" handing a question to support twice.
"""

import pytest

from apps.kb.models import KbArticle
from apps.review.models import ReviewItem
from apps.tickets.models import AiRun, RoutingDecision, Ticket, TicketSource
from apps.tickets.utils.pipeline import ticket_process
from apps.tickets.utils.patterns import PIILevel


@pytest.fixture
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@pytest.fixture
def enqueued(monkeypatch):
    """Stands in for the Celery task; tests run the pipeline themselves."""
    ids: list[str] = []

    class Fake:
        def delay(self, ticket_id: str) -> None:
            ids.append(ticket_id)

    monkeypatch.setattr("apps.tickets.tasks.process_ticket", Fake())
    return ids


@pytest.fixture
def live(settings):
    settings.SHADOW_MODE = False


def ask(client, message: str):
    return client.post("/api/chat/ask", {"message": message}, content_type="application/json")


@pytest.mark.django_db
class TestAsk:
    def test_question_becomes_a_chat_ticket_and_is_thinking(
        self, employee_user, api_as, ner_finds_nothing, enqueued
    ):
        response = ask(api_as(employee_user), "My VPN keeps timing out since this morning")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "thinking"
        assert body["answer"] is None
        ticket = Ticket.objects.get(public_id=body["public_id"])
        assert ticket.source == TicketSource.CHAT.value
        assert enqueued == [str(ticket.id)]

    def test_question_is_masked_like_any_ticket(
        self, employee_user, api_as, ner_finds_nothing, enqueued
    ):
        body = ask(api_as(employee_user), "Please email me at an.nguyen@example.com").json()

        assert "an.nguyen@example.com" not in body["question_masked"]
        assert "[EMAIL_1]" in body["question_masked"]

    def test_too_short_is_rejected_before_masking(self, employee_user, api_as, enqueued):
        assert ask(api_as(employee_user), "help").status_code == 422
        assert not Ticket.objects.exists()


@pytest.mark.django_db
class TestShadowMode:
    def test_question_goes_to_support_without_a_suggestion(
        self, employee_user, api_as, ner_finds_nothing, enqueued, settings
    ):
        settings.SHADOW_MODE = True
        client = api_as(employee_user)
        public_id = ask(client, "My VPN keeps timing out since this morning").json()["public_id"]
        ticket_process(enqueued[0])

        assert client.get(f"/api/chat/tickets/{public_id}").json()["state"] == "with_support"
        assert ReviewItem.objects.filter(ticket__public_id=public_id).count() == 1
        assert client.post(f"/api/chat/tickets/{public_id}/create-ticket").status_code == 409


@pytest.mark.django_db
@pytest.mark.usefixtures("live")
class TestSuggestAndCreateTicket:
    def test_handoff_is_suggested_then_created_once(
        self, employee_user, api_as, ner_finds_nothing, enqueued
    ):
        client = api_as(employee_user)
        public_id = ask(client, "My VPN keeps timing out since this morning").json()["public_id"]
        ticket_process(enqueued[0])

        assert client.get(f"/api/chat/tickets/{public_id}").json()["state"] == "suggest_ticket"

        created = client.post(f"/api/chat/tickets/{public_id}/create-ticket")
        assert created.status_code == 200
        assert created.json()["state"] == "with_support"
        assert ReviewItem.objects.filter(ticket__public_id=public_id).count() == 1

        again = client.post(f"/api/chat/tickets/{public_id}/create-ticket")
        assert again.status_code == 409
        assert ReviewItem.objects.filter(ticket__public_id=public_id).count() == 1


@pytest.mark.django_db
@pytest.mark.usefixtures("live")
class TestOwnership:
    def test_another_requesters_conversation_is_not_found(
        self, employee_user, technician_user, api_as, ner_finds_nothing, enqueued
    ):
        public_id = ask(api_as(employee_user), "My VPN keeps timing out").json()["public_id"]
        ticket_process(enqueued[0])
        other = api_as(technician_user)

        assert other.get(f"/api/chat/tickets/{public_id}").status_code == 404
        assert other.post(f"/api/chat/tickets/{public_id}/create-ticket").status_code == 404
        assert other.get("/api/chat/tickets").json() == []
        assert not ReviewItem.objects.exists()

    def test_form_tickets_are_not_in_the_chat(self, employee_user, api_as):
        Ticket.objects.create(
            public_id="TKT-FORM-1",
            reporter=employee_user,
            subject_masked="s",
            body_masked="b",
            pii_level=PIILevel.ROUTINE.value,
        )
        client = api_as(employee_user)

        assert client.get("/api/chat/tickets").json() == []
        assert client.get("/api/chat/tickets/TKT-FORM-1").status_code == 404


def _auto_replied_chat_ticket(reporter, status: str) -> Ticket:
    ticket = Ticket.objects.create(
        public_id="TKT-CHAT-ANS",
        reporter=reporter,
        subject_masked="Reset MFA",
        body_masked="How do I reset my MFA device?",
        pii_level=PIILevel.ROUTINE.value,
        source=TicketSource.CHAT.value,
        status=status,
    )
    run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="t",
        model="t",
        graph_version="t",
        trust_signals={},
        proposed_draft={
            "proposed_intent": "auto_reply",
            "kb_slug": "kb-mfa",
            "verbatim_quote": "Choose Remove MFA device, then assign a new one.",
            "answer_draft": "Open the IAM console and remove the old device first.",
            "self_confidence": 0.9,
        },
    )
    RoutingDecision.objects.create(
        ticket=ticket,
        ai_run=run,
        branch="auto_reply",
        reason_code="all_checks_passed",
        reason_detail="",
        thresholds_used={},
        shadow_mode=False,
    )
    return ticket


@pytest.mark.django_db
class TestAnswer:
    def test_auto_replied_ticket_shows_the_answer_and_its_page(self, employee_user, api_as):
        KbArticle.objects.create(
            slug="kb-mfa",
            title="Resetting an MFA device",
            body="...",
            category="access",
            source_url="https://docs.example.com/mfa",
        )
        _auto_replied_chat_ticket(employee_user, status="auto_replied")

        body = api_as(employee_user).get("/api/chat/tickets/TKT-CHAT-ANS").json()

        assert body["state"] == "answered"
        assert body["answer"] == {
            "text": "Open the IAM console and remove the old device first.",
            "quote": "Choose Remove MFA device, then assign a new one.",
            "kb_title": "Resetting an MFA device",
            "kb_url": "https://docs.example.com/mfa",
        }

    def test_a_proposal_alone_is_never_shown(self, employee_user, api_as):
        """The answer is shown because the ticket was auto-replied, not
        because the run proposed one: a held or reviewed ticket with an
        auto-reply proposal shows no answer."""
        _auto_replied_chat_ticket(employee_user, status="awaiting_requester")

        body = api_as(employee_user).get("/api/chat/tickets/TKT-CHAT-ANS").json()

        assert body["state"] == "suggest_ticket"
        assert body["answer"] is None


def _asked_chat_ticket(reporter, *, asked_minutes_ago: int = 0) -> Ticket:
    """A live chat ticket whose clarify decision is held and whose question
    is open, as the pipeline leaves it (ADR-0023)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.tickets.models import TicketClarification

    ticket = Ticket.objects.create(
        public_id="TKT-CHAT-CLR",
        reporter=reporter,
        subject_masked="The client app keeps crashing",
        body_masked="The client app keeps crashing on my laptop.",
        pii_level=PIILevel.ROUTINE.value,
        source=TicketSource.CHAT.value,
        status="awaiting_requester",
        held_decision={"branch": "clarify", "reason_code": "all_checks_passed"},
    )
    asked = TicketClarification.objects.create(
        ticket=ticket,
        question="Which application keeps crashing?",
        options=[
            {"slug": "client-vpn-user.windows-troubleshooting", "title": "AWS VPN Client"},
            {"slug": "workspaces-user.client_troubleshooting", "title": "WorkSpaces client"},
        ],
        ticket_body_masked=ticket.body_masked,
    )
    TicketClarification.objects.filter(id=asked.id).update(
        asked_at=timezone.now() - timedelta(minutes=asked_minutes_ago)
    )
    return ticket


def answer(client, public_id: str, text: str):
    return client.post(
        f"/api/chat/tickets/{public_id}/clarify", {"answer": text}, content_type="application/json"
    )


@pytest.mark.django_db
class TestClarify:
    def test_open_question_shows_with_page_titles_never_slugs(self, employee_user, api_as):
        _asked_chat_ticket(employee_user)

        body = api_as(employee_user).get("/api/chat/tickets/TKT-CHAT-CLR").json()

        assert body["state"] == "clarify"
        assert body["clarification"] == {
            "question": "Which application keeps crashing?",
            "options": ["AWS VPN Client", "WorkSpaces client"],
            "answer_masked": None,
        }

    def test_answer_shows_the_original_question_and_thinks_again(
        self, employee_user, api_as, ner_finds_nothing, enqueued
    ):
        ticket = _asked_chat_ticket(employee_user)

        response = answer(api_as(employee_user), "TKT-CHAT-CLR", "AWS VPN Client")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "thinking"
        # What the requester typed, not the body with the answer appended.
        assert body["question_masked"] == "The client app keeps crashing on my laptop."
        assert body["clarification"]["answer_masked"] == "AWS VPN Client"
        assert enqueued == [str(ticket.id)]

    def test_expired_question_offers_a_ticket_and_refuses_an_answer(
        self, employee_user, api_as, settings, enqueued
    ):
        wait = settings.THRESHOLDS.clarification.wait_minutes
        _asked_chat_ticket(employee_user, asked_minutes_ago=wait)
        client = api_as(employee_user)

        assert client.get("/api/chat/tickets/TKT-CHAT-CLR").json()["state"] == "suggest_ticket"
        assert answer(client, "TKT-CHAT-CLR", "AWS VPN Client").status_code == 409
        assert enqueued == []

    def test_another_requester_cannot_answer(self, employee_user, technician_user, api_as):
        _asked_chat_ticket(employee_user)

        assert answer(api_as(technician_user), "TKT-CHAT-CLR", "VPN").status_code == 404

    def test_an_empty_answer_is_rejected_before_masking(self, employee_user, api_as, enqueued):
        _asked_chat_ticket(employee_user)

        assert answer(api_as(employee_user), "TKT-CHAT-CLR", "   ").status_code == 422
        assert enqueued == []


@pytest.mark.django_db
def test_a_turn_tells_the_requester_where_support_has_it(employee_user):
    from apps.chat.utils import chat_turn
    from apps.lifecycle.tests.conftest import make_ticket
    from apps.lifecycle.utils.vocabulary import PipelineStatus
    from apps.tickets.models import TicketSource

    ticket = make_ticket(employee_user, at=PipelineStatus.AUTO_REPLIED)
    ticket.source = TicketSource.CHAT.value
    ticket.save(update_fields=["source"])

    turn = chat_turn(ticket)

    assert turn.status_name == "Auto-replied"
    assert turn.resolved is True
