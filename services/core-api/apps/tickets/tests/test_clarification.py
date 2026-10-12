"""
A live chat ticket asks its requester the clarifying question (ADR-0023).

What can go wrong quietly here: a question asked again and again of a
requester who can't say more; an answer that skips masking or the hard
gates because it arrived after the ticket did; an answer reusing the
ticket's placeholder numbers; a double submit running the pipeline twice;
an expired question still taking answers; and shadow mode or a form ticket
starting to ask questions nobody approved.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.kb.models import KbArticle
from apps.review.models import ReviewItem
from apps.tickets.models import IncidentVerdict, PiiQuarantine, Ticket, TicketSource
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.pipeline import (
    NotAwaitingAnswer,
    answer_clarification,
    release_to_support,
    ticket_process,
)
from apps.tickets.utils.router import Branch, ReasonCode, ReviewQueue
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import (
    AIRunResponse,
    ClassificationSignals,
    EngineSignals,
    GenerationSignals,
    LLMProposalEnvelope,
    RetrievalSignals,
    TicketCategory,
)

VPN = "client-vpn-user.windows-troubleshooting"
WORKSPACES = "workspaces-user.client_troubleshooting"


def _clarify_response(request_id: str) -> AIRunResponse:
    """ai-engine proposing a question whose options it was shown, on a
    confident non-security category: the router chooses `clarify`."""
    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="test",
        proposal=LLMProposalEnvelope.model_validate(
            {
                "proposed_intent": "clarify",
                "proposed_question": "Which application keeps crashing?",
                "proposed_options": [VPN, WORKSPACES],
                "rationale": "names no application",
            }
        ),
        signals=EngineSignals(
            retrieval=RetrievalSignals(rerank_top1=0.9, rerank_margin=0.0, docs_above_floor=2),
            generation=GenerationSignals(
                quote_match_ratio=0.0,
                quote_source_in_topk=False,
                negation_consistent=False,
                clarify_options_in_topk=True,
            ),
            classification=ClassificationSignals(
                category_choice=TicketCategory.SOFTWARE, category_confidence=0.9
            ),
            injection_detected=False,
        ),
    )


@pytest.fixture
def kb_pages(db):
    for slug, title in [(VPN, "AWS VPN Client on Windows"), (WORKSPACES, "WorkSpaces client")]:
        KbArticle.objects.create(slug=slug, title=title, body="x", category="software")


@pytest.fixture
def engine_always_clarifies(monkeypatch):
    """ai-engine proposes the question on every run; the bodies it was sent
    are kept, so a test can check the answer reached the second run."""
    sent: list[str] = []

    def analyze(masked, request_id):
        sent.append(masked.body_masked)
        return _clarify_response(request_id)

    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(Ticket, "classify_similarity", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(ai_engine, "analyze", analyze)
    return sent


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


def _chat_ticket(reporter, *, pii_map: dict[str, str] | None = None) -> Ticket:
    return Ticket.objects.create(
        public_id="TKT-TEST-CLR-001",
        reporter=reporter,
        subject_masked="The client app keeps crashing",
        body_masked="The client app keeps crashing on my laptop.",
        pii_level=PIILevel.ROUTINE.value,
        pii_map=pii_map or {},
        source=TicketSource.CHAT.value,
    )


@pytest.fixture
def live(settings):
    settings.SHADOW_MODE = False


@pytest.mark.django_db
class TestAsking:
    def test_live_chat_clarify_asks_the_requester(
        self, employee_user, kb_pages, engine_always_clarifies, live
    ):
        ticket = _chat_ticket(employee_user)

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "awaiting_requester"
        assert not ticket.review_items.exists()
        asked = ticket.clarifications.get()
        assert asked.question == "Which application keeps crashing?"
        assert asked.options == [
            {"slug": VPN, "title": "AWS VPN Client on Windows"},
            {"slug": WORKSPACES, "title": "WorkSpaces client"},
        ]
        assert asked.ai_run == ticket.routing_decisions.get().ai_run
        assert ticket.open_clarification() == asked
        assert AuditLog.objects.filter(ticket_id=ticket.id, event="clarification_asked").exists()

    def test_shadow_mode_asks_nothing(
        self, employee_user, kb_pages, engine_always_clarifies, settings
    ):
        """Shadow mode sends nothing (spec §14 P1); a question is something
        sent. The requester is offered a ticket, as before ADR-0023."""
        settings.SHADOW_MODE = True
        ticket = _chat_ticket(employee_user)

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "awaiting_requester"
        assert not ticket.clarifications.exists()

    def test_asking_for_a_person_instead_reaches_the_clarification_queue(
        self, employee_user, kb_pages, engine_always_clarifies, live
    ):
        """The decision stays held while the question is open, so "talk to
        a person" carries it out exactly as before ADR-0023."""
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))

        release_to_support(ticket.id, employee_user.id, None)

        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ticket.open_clarification() is None
        item = ReviewItem.objects.get(ticket=ticket)
        assert item.queue == ReviewQueue.CLARIFICATION.value


@pytest.mark.django_db
class TestAnswering:
    def test_answer_reruns_the_pipeline_on_question_and_answer(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))

        answer_clarification(ticket.id, employee_user.id, "The AWS VPN one", None)

        ticket.refresh_from_db()
        assert ticket.status == "new"
        assert ticket.held_decision is None
        assert ticket.body_masked.endswith(
            "\n\nAsked: Which application keeps crashing?\nAnswered: The AWS VPN one"
        )
        assert enqueued == [str(ticket.id)]
        asked = ticket.clarifications.get()
        assert asked.answer_masked == "The AWS VPN one"
        assert asked.ticket_body_masked == "The client app keeps crashing on my laptop."

        ticket_process(str(ticket.id))
        assert "Answered: The AWS VPN one" in engine_always_clarifies[-1]

    def test_still_ambiguous_after_the_answer_goes_to_a_person(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        """One question, then a human: the second run's clarify proposal is
        refused by the round cap, and no second question is asked."""
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))
        answer_clarification(ticket.id, employee_user.id, "not sure", None)

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        latest = ticket.routing_decisions.latest("decided_at")
        assert latest.branch == Branch.HITL.value
        assert latest.reason_code == ReasonCode.CLARIFY_ROUND_CAP.value
        assert ticket.clarifications.count() == 1
        second_run = ticket.ai_runs.latest("created_at")
        assert second_run.trust_signals["policy"]["clarifications_asked"] == 1

    def test_answer_is_masked_and_continues_the_tickets_numbering(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user, pii_map={"[EMAIL_1]": "ref-of-the-ticket"})
        ticket_process(str(ticket.id))

        answer_clarification(ticket.id, employee_user.id, "VPN, mail b.tran@company.com", None)

        ticket.refresh_from_db()
        asked = ticket.clarifications.get()
        assert asked.answer_masked == "VPN, mail [EMAIL_2]"
        assert "b.tran@company.com" not in ticket.body_masked
        assert ticket.pii_map["[EMAIL_1]"] == "ref-of-the-ticket"
        assert PiiQuarantine.objects.filter(ticket=ticket, ref=ticket.pii_map["[EMAIL_2]"]).exists()

    def test_answer_with_a_password_blocks_the_ticket(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        """The answer is untrusted input like the ticket: critical PII in it
        makes the ticket critical, and the re-run's hard gate blocks it,
        with no waiting on the requester."""
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))

        answer_clarification(ticket.id, employee_user.id, "VPN. password: hunter2", None)
        ticket.refresh_from_db()
        assert ticket.pii_level == PIILevel.CRITICAL.value

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "blocked"
        latest = ticket.routing_decisions.latest("decided_at")
        assert latest.reason_code == ReasonCode.PII_CRITICAL.value

    def test_answer_ner_cannot_mask_sends_the_ticket_to_a_person(
        self, employee_user, kb_pages, engine_always_clarifies, enqueued, live
    ):
        """The autouse offline ai-engine fails NER: MASK_FAILED, never "the
        answer had no PII"."""
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))

        answer_clarification(ticket.id, employee_user.id, "the VPN client", None)

        ticket.refresh_from_db()
        assert ticket.pii_level == PIILevel.MASK_FAILED.value
        ticket_process(str(ticket.id))
        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ReviewItem.objects.filter(ticket=ticket).exists()

    def test_an_answer_never_lowers_the_pii_level(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user)
        ticket.pii_level = PIILevel.SENSITIVE.value
        ticket.save(update_fields=["pii_level"])
        ticket_process(str(ticket.id))

        answer_clarification(ticket.id, employee_user.id, "the VPN client", None)

        ticket.refresh_from_db()
        assert ticket.pii_level == PIILevel.SENSITIVE.value

    def test_a_second_answer_is_refused(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))
        answer_clarification(ticket.id, employee_user.id, "VPN", None)

        with pytest.raises(NotAwaitingAnswer):
            answer_clarification(ticket.id, employee_user.id, "WorkSpaces", None)
        assert enqueued == [str(ticket.id)]

    def test_an_expired_question_takes_no_answer(
        self,
        employee_user,
        kb_pages,
        engine_always_clarifies,
        ner_finds_nothing,
        enqueued,
        live,
        settings,
    ):
        """After `clarification.wait_minutes` the chat offers a ticket
        instead (the user's choice for ADR-0023): nothing goes to support
        on its own, and a late answer is refused rather than re-running."""
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))
        wait = settings.THRESHOLDS.clarification.wait_minutes
        ticket.clarifications.update(asked_at=timezone.now() - timedelta(minutes=wait))

        assert ticket.open_clarification() is None
        with pytest.raises(NotAwaitingAnswer):
            answer_clarification(ticket.id, employee_user.id, "VPN", None)
        assert enqueued == []
        ticket.refresh_from_db()
        assert ticket.status == "awaiting_requester"
        assert not ReviewItem.objects.filter(ticket=ticket).exists()

    def test_no_question_asked_takes_no_answer(self, employee_user, enqueued):
        ticket = _chat_ticket(employee_user)

        with pytest.raises(NotAwaitingAnswer):
            answer_clarification(ticket.id, employee_user.id, "VPN", None)
        assert enqueued == []
