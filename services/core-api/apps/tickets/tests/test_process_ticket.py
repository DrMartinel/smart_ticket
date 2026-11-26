"""
process_ticket — spec §10.3's overarching rule: any degradation must fail
open to a human, never fail silent. AIEngineUnavailable already had that
fallback; the embedding call ahead of it (used for incident/duplicate
detection) did not — an embedding outage there raised an uncaught exception
straight out of the Celery task, leaving the ticket stuck at status="new"
forever with no RoutingDecision and no ReviewItem, invisible to every
queue and dashboard. This is the regression test for that fix.
"""

import httpx
import pytest

from apps.incidents.services.incidents import incidents
from apps.tickets.domain.router import Branch, ReasonCode
from apps.tickets.domain.patterns import PIILevel

from apps.tickets.models import Ticket
from apps.tickets.tasks import process_ticket
from infrastructure.ai_engine import ai_engine


def make_ticket(reporter) -> Ticket:
    return Ticket.objects.create(
        public_id="TKT-TEST-EMB-001",
        reporter=reporter,
        subject_masked="May tinh khong vao duoc mang",
        body_masked="Tu sang nay may tinh cua toi khong ket noi duoc mang noi bo",
        pii_level=PIILevel.ROUTINE.value,
    )


@pytest.mark.django_db
class TestEmbeddingFailureFailsOpenToHitl:
    def test_connect_timeout_produces_hitl_routing_decision(self, employee_user, serve_ai_engine):
        ticket = make_ticket(employee_user)

        def raise_timeout(request):
            raise httpx.ConnectTimeout("simulated: ai-engine unreachable")

        serve_ai_engine(raise_timeout)

        result = process_ticket.apply(args=(ticket.id,)).get()

        assert result["branch"] == Branch.HITL.value

        ticket.refresh_from_db()
        decision = ticket.routing_decisions.order_by("-id").first()
        assert decision is not None
        assert decision.branch == Branch.HITL.value
        assert decision.reason_code == ReasonCode.EMBEDDING_UNAVAILABLE.value

        review_item = ticket.review_items.order_by("-id").first()
        assert review_item is not None, "ticket must land in a review queue, not vanish silently"

    def test_ticket_never_left_stuck_at_new_status(self, employee_user, serve_ai_engine):
        ticket = make_ticket(employee_user)
        serve_ai_engine(lambda request: httpx.Response(502, json={"detail": "embedder failed"}))

        process_ticket.apply(args=(ticket.id,)).get()

        ticket.refresh_from_db()
        assert ticket.status != "new"


def _no_findings():
    """ai-engine's signals with every check failed and nothing found."""

    from infrastructure.dtos import EngineSignals

    from apps.tickets.services.pipeline import _degraded_signals

    d = _degraded_signals()
    return EngineSignals(
        retrieval=d.retrieval,
        generation=d.generation,
        classification=d.classification,
        injection_detected=False,
    )


def _llm_failed_response(reason: str, request_id: str):
    """What ai-engine returns when its chat LLM call failed: no proposal,
    and `reason` as the degraded_reason."""

    from infrastructure.dtos import AIRunResponse

    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="n/a",
        proposal=None,
        signals=_no_findings(),
        degraded_reason=reason,
    )


@pytest.mark.django_db
class TestLlmFailureKeepsItsReasonCode:
    """Before this branch existed, core-api sent an LLM outage through the
    router, which sees only proposal=None and labelled it SCHEMA_INVALID —
    indistinguishable on the dashboard from "the model returned bad JSON"."""

    def test_llm_failure_reaches_hitl_as_all_llm_down(self, employee_user, monkeypatch):
        reason = ReasonCode.ALL_LLM_DOWN
        from apps.tickets.models import IncidentVerdict

        ticket = make_ticket(employee_user)
        monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
        monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
        monkeypatch.setattr(
            ai_engine,
            "analyze",
            lambda masked, request_id, categories: _llm_failed_response(reason.value, request_id),
        )

        result = process_ticket.apply(args=(ticket.id,)).get()

        assert result["branch"] == Branch.HITL.value
        decision = ticket.routing_decisions.order_by("-id").first()
        assert decision is not None
        assert decision.reason_code == reason.value
        assert ticket.review_items.exists(), "must land in a review queue"
        ai_run = ticket.ai_runs.order_by("-id").first()
        assert ai_run is not None
        assert ai_run.degraded_reason == reason.value


def _clarify_response(request_id: str):
    """ai-engine proposing a question whose options it was shown."""

    from infrastructure.dtos import AIRunResponse, LLMProposalEnvelope

    signals = _no_findings()
    signals.retrieval.rerank_top1 = 0.9
    signals.retrieval.rerank_total = 0.95
    signals.generation.clarify_options_in_topk = True
    # Jev's category, confident: without it the router sends the ticket to a
    # human as category_low_confidence (ADR-0017).
    signals.classification.category_choice = "software"
    signals.classification.category_confidence = 0.9
    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="test",
        proposal=LLMProposalEnvelope.model_validate(
            {
                "proposed_intent": "clarify",
                "proposed_question": "Which application keeps crashing?",
                "proposed_options": [
                    "client-vpn-user.windows-troubleshooting",
                    "workspaces-user.client_troubleshooting",
                ],
                "rationale": "names no application",
            }
        ),
        signals=signals,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("shadow", [True, False])
def test_clarify_reaches_a_person_in_the_clarification_queue(
    shadow, employee_user, monkeypatch, settings
):
    """Checks that a form ticket's clarify decision becomes a review item in
    the clarification queue, live or in shadow (ADR-0023)."""
    from apps.tickets.models import IncidentVerdict

    settings.SHADOW_MODE = shadow
    ticket = make_ticket(employee_user)
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(
        ai_engine, "analyze", lambda masked, request_id, categories: _clarify_response(request_id)
    )

    result = process_ticket.apply(args=(ticket.id,)).get()

    assert result["branch"] == Branch.CLARIFY.value
    ticket.refresh_from_db()
    assert ticket.status == "pending_review"
    assert list(ticket.review_items.values_list("queue", flat=True)) == ["clarification"]


@pytest.mark.django_db
class TestCategorySet:
    """Triage reads the active categories at every run (ADR-0049)."""

    @pytest.fixture
    def sent(self, monkeypatch):
        from apps.tickets.models import IncidentVerdict

        offered: list = []
        monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
        monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))

        def analyze(masked, request_id, categories):
            offered.append(categories)
            return _llm_failed_response(ReasonCode.ALL_LLM_DOWN.value, request_id)

        monkeypatch.setattr(ai_engine, "analyze", analyze)
        return offered

    def test_ai_engine_is_offered_the_active_categories_in_slug_order(self, employee_user, sent):
        from apps.categories.models import Category

        Category.objects.filter(slug="other").update(is_active=False)

        process_ticket.apply(args=(make_ticket(employee_user).id,)).get()

        [offered] = sent
        assert [c.slug for c in offered] == [
            "access",
            "hardware",
            "network",
            "security",
            "software",
        ]
        network = Category.objects.get(slug="network")
        assert offered[2].description == network.description

    def test_a_set_with_no_security_category_reaches_a_person_without_ai_engine(
        self, employee_user, sent
    ):
        from apps.categories.models import Category

        Category.objects.update(is_security=False)
        ticket = make_ticket(employee_user)

        result = process_ticket.apply(args=(ticket.id,)).get()

        assert sent == []
        assert result["branch"] == Branch.HITL.value
        decision = ticket.routing_decisions.get()
        assert decision.reason_code == ReasonCode.CATEGORY_SET_INVALID.value
        assert ticket.ai_runs.get().degraded_reason == "category_set_invalid"
        assert ticket.review_items.exists(), "must land in a review queue"

    @pytest.mark.parametrize(
        "pii_level, branch, reason",
        [
            (PIILevel.CRITICAL, Branch.BLOCK, ReasonCode.PII_CRITICAL),
            (PIILevel.MASK_FAILED, Branch.HITL, ReasonCode.PII_MASK_FAILED),
        ],
    )
    def test_an_unusable_set_still_lets_the_earlier_gates_decide(
        self, employee_user, sent, pii_level, branch, reason
    ):
        from apps.categories.models import Category

        Category.objects.update(is_security=False)
        ticket = make_ticket(employee_user)
        Ticket.objects.filter(pk=ticket.pk).update(pii_level=pii_level.value)

        result = process_ticket.apply(args=(ticket.id,)).get()

        assert sent == []
        assert result["branch"] == branch.value
        assert ticket.routing_decisions.get().reason_code == reason.value

    def test_a_decision_records_the_categories_it_ran_against(self, employee_user, sent):
        ticket = make_ticket(employee_user)

        process_ticket.apply(args=(ticket.id,)).get()

        used = ticket.routing_decisions.get().categories_used
        assert [c["slug"] for c in used] == [
            "access",
            "hardware",
            "network",
            "other",
            "security",
            "software",
        ]
        assert {"slug": "security", "is_security": True, "is_routable": True, "version": 1} in used
