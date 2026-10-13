"""
Checks how a live chat ticket asks its requester the clarifying question
and takes the answer (ADR-0023).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from config.settings.base import ClarificationThresholds

from apps.audit.models import AuditLog
from apps.kb.models import KbArticle
from apps.review.models import ReviewItem
from apps.tickets.models import IncidentVerdict, PiiQuarantine, Ticket, TicketSource
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.clarification import (
    CLARIFY_QUESTION,
    Clarifications,
    NotAwaitingAnswer,
    clarifications,
)
from apps.tickets.utils.pipeline import release_to_support, ticket_process
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
VPN_ADMIN = "client-vpn-admin.troubleshooting"

# Jev's top 5 as ai-engine reports them, in Jev's order: two pages within
# 0.1 of the best, an administrator page well below it.
CLOSE_TOP5 = [
    {"kb_slug": VPN, "rerank_score": 0.95},
    {"kb_slug": WORKSPACES, "rerank_score": 0.90},
    {"kb_slug": VPN_ADMIN, "rerank_score": 0.40},
]


def _clarify_response(request_id: str, top5=CLOSE_TOP5) -> AIRunResponse:
    """ai-engine proposing a question whose options it was shown, on a
    confident non-security category: the router chooses `clarify`."""
    return AIRunResponse(
        retrieved_chunks=top5,
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
    for slug, title in [
        (VPN, "AWS VPN Client on Windows"),
        (WORKSPACES, "WorkSpaces client"),
        (VPN_ADMIN, "Client VPN troubleshooting for administrators"),
    ]:
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
        # The fixed question, never the model's ("Which application keeps
        # crashing?"), which can name readings the buttons don't offer.
        assert asked.question == CLARIFY_QUESTION
        # Built from Jev's top 5 within 0.1 of the best, in Jev's order;
        # the administrator page at 0.40 is left out.
        assert asked.options == [
            {"slug": VPN, "title": "AWS VPN Client on Windows"},
            {"slug": WORKSPACES, "title": "WorkSpaces client"},
        ]
        assert asked.ai_run == ticket.routing_decisions.get().ai_run
        assert ticket.open_clarification() == asked
        assert AuditLog.objects.filter(ticket_id=ticket.id, event="clarification_asked").exists()

    def test_fewer_than_two_close_pages_asks_nothing_and_a_person_gets_it(
        self, employee_user, kb_pages, monkeypatch, live
    ):
        monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
        monkeypatch.setattr(
            Ticket, "classify_similarity", lambda *a: IncidentVerdict(kind="unique")
        )
        far = [{"kb_slug": VPN, "rerank_score": 0.95}, {"kb_slug": WORKSPACES, "rerank_score": 0.5}]
        monkeypatch.setattr(
            ai_engine, "analyze", lambda masked, request_id: _clarify_response(request_id, far)
        )
        ticket = _chat_ticket(employee_user)

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ticket.held_decision is None
        assert not ticket.clarifications.exists()
        assert list(ticket.review_items.values_list("queue", flat=True)) == ["clarification"]

    def test_shadow_mode_asks_nothing(
        self, employee_user, kb_pages, engine_always_clarifies, settings
    ):
        settings.SHADOW_MODE = True
        ticket = _chat_ticket(employee_user)

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "awaiting_requester"
        assert not ticket.clarifications.exists()

    def test_asking_for_a_person_instead_reaches_the_clarification_queue(
        self, employee_user, kb_pages, engine_always_clarifies, live
    ):
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

        clarifications.answer(ticket.id, employee_user.id, "The AWS VPN one", None)

        ticket.refresh_from_db()
        assert ticket.status == "new"
        assert ticket.held_decision is None
        # The answer only: the question named every reading, and appended it
        # pulled the next run back toward all of them.
        assert ticket.body_masked == (
            "The client app keeps crashing on my laptop.\n\nRequester clarified: The AWS VPN one"
        )
        assert enqueued == [str(ticket.id)]
        asked = ticket.clarifications.get()
        assert asked.answer_masked == "The AWS VPN one"
        assert asked.ticket_body_masked == "The client app keeps crashing on my laptop."

        ticket_process(str(ticket.id))
        assert "Requester clarified: The AWS VPN one" in engine_always_clarifies[-1]

    def test_still_ambiguous_after_the_answer_goes_to_a_person(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))
        clarifications.answer(ticket.id, employee_user.id, "not sure", None)

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

        clarifications.answer(ticket.id, employee_user.id, "VPN, mail b.tran@company.com", None)

        ticket.refresh_from_db()
        asked = ticket.clarifications.get()
        assert asked.answer_masked == "VPN, mail [EMAIL_2]"
        assert "b.tran@company.com" not in ticket.body_masked
        assert ticket.pii_map["[EMAIL_1]"] == "ref-of-the-ticket"
        assert PiiQuarantine.objects.filter(ticket=ticket, ref=ticket.pii_map["[EMAIL_2]"]).exists()

    def test_answer_with_a_password_blocks_the_ticket(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))

        clarifications.answer(ticket.id, employee_user.id, "VPN. password: hunter2", None)
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
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))

        clarifications.answer(ticket.id, employee_user.id, "the VPN client", None)

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

        clarifications.answer(ticket.id, employee_user.id, "the VPN client", None)

        ticket.refresh_from_db()
        assert ticket.pii_level == PIILevel.SENSITIVE.value

    def test_a_second_answer_is_refused(
        self, employee_user, kb_pages, engine_always_clarifies, ner_finds_nothing, enqueued, live
    ):
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))
        clarifications.answer(ticket.id, employee_user.id, "VPN", None)

        with pytest.raises(NotAwaitingAnswer):
            clarifications.answer(ticket.id, employee_user.id, "WorkSpaces", None)
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
        ticket = _chat_ticket(employee_user)
        ticket_process(str(ticket.id))
        wait = settings.THRESHOLDS.clarification.wait_minutes
        ticket.clarifications.update(asked_at=timezone.now() - timedelta(minutes=wait))

        assert ticket.open_clarification() is None
        with pytest.raises(NotAwaitingAnswer):
            clarifications.answer(ticket.id, employee_user.id, "VPN", None)
        assert enqueued == []
        ticket.refresh_from_db()
        assert ticket.status == "awaiting_requester"
        assert not ReviewItem.objects.filter(ticket=ticket).exists()

    def test_no_question_asked_takes_no_answer(self, employee_user, enqueued):
        ticket = _chat_ticket(employee_user)

        with pytest.raises(NotAwaitingAnswer):
            clarifications.answer(ticket.id, employee_user.id, "VPN", None)
        assert enqueued == []


def _th(margin: float, max_options: int) -> ClarificationThresholds:
    return ClarificationThresholds(
        max_rounds=1, wait_minutes=60, option_margin=margin, max_options=max_options
    )


class TestClarifyOptions:
    """Checks which pages `Clarifications.options` offers from Jev's ranking."""

    TITLES = {"a": "Page A", "b": "Page B", "c": "Page C", "d": "Page D", "e": "Page E"}

    def test_pages_within_the_margin_of_jevs_best_in_jevs_order(self):
        chunks = [
            {"kb_slug": "a", "rerank_score": 0.97},
            {"kb_slug": "b", "rerank_score": 0.96},
            {"kb_slug": "c", "rerank_score": 0.87},
            {"kb_slug": "d", "rerank_score": 0.79},
            {"kb_slug": "e", "rerank_score": 0.76},
        ]
        assert [o["slug"] for o in Clarifications.options(chunks, self.TITLES, _th(0.1, 5))] == [
            "a",
            "b",
            "c",
        ]

    @pytest.mark.parametrize("best, at_margin", [(0.97, 0.87), (0.8, 0.7), (0.3, 0.2)])
    def test_a_page_exactly_at_the_margin_is_offered(self, best, at_margin):
        chunks = [
            {"kb_slug": "a", "rerank_score": best},
            {"kb_slug": "b", "rerank_score": at_margin},
        ]
        assert [o["slug"] for o in Clarifications.options(chunks, self.TITLES, _th(0.1, 5))] == [
            "a",
            "b",
        ]

    def test_capped_at_max_options(self):
        chunks = [{"kb_slug": s, "rerank_score": 0.9} for s in "abcde"]
        assert len(Clarifications.options(chunks, self.TITLES, _th(0.1, 4))) == 4

    def test_one_button_per_page(self):
        chunks = [
            {"kb_slug": "a", "rerank_score": 0.9},
            {"kb_slug": "a", "rerank_score": 0.88},
            {"kb_slug": "b", "rerank_score": 0.85},
        ]
        assert [o["slug"] for o in Clarifications.options(chunks, self.TITLES, _th(0.1, 5))] == [
            "a",
            "b",
        ]

    def test_an_inactive_page_is_never_offered(self):
        chunks = [{"kb_slug": "a", "rerank_score": 0.9}, {"kb_slug": "gone", "rerank_score": 0.9}]
        assert [o["slug"] for o in Clarifications.options(chunks, self.TITLES, _th(0.1, 5))] == [
            "a"
        ]

    def test_no_chunks_no_options(self):
        assert Clarifications.options([], self.TITLES, _th(0.1, 5)) == []
