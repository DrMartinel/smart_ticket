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
