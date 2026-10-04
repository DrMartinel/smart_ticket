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

from apps.tickets.utils.router import Branch, ReasonCode
from apps.tickets.utils.patterns import PIILevel

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


def _llm_failed_response(reason: str, request_id: str):
    """What ai-engine returns when its chat LLM call failed: no proposal,
    and `reason` as the degraded_reason."""

    from infrastructure.dtos import AIRunResponse

    from apps.tickets.utils.pipeline import _degraded_signals

    return AIRunResponse(
        request_id=request_id,
        graph_version="test",
        prompt_version="test",
        model="n/a",
        proposal=None,
        signals=_degraded_signals(),
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
        monkeypatch.setattr(
            Ticket, "classify_similarity", lambda *a: IncidentVerdict(kind="unique")
        )
        monkeypatch.setattr(
            ai_engine,
            "analyze",
            lambda masked, request_id: _llm_failed_response(reason.value, request_id),
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

    from infrastructure.dtos import AIRunResponse, LLMProposalEnvelope, TicketCategory

    from apps.tickets.utils.pipeline import _degraded_signals

    signals = _degraded_signals()
    signals.retrieval.rerank_top1 = 0.9
    signals.retrieval.scorer = "jev"
    signals.generation.schema_valid = True
    signals.generation.clarify_options_in_topk = True
    # Jev's category, confident: without it the router sends the ticket to a
    # human as category_low_confidence (ADR-0017).
    signals.classification.category_choice = TicketCategory.SOFTWARE
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
                "proposed_category": "software",
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
    """Nothing sends a question to the requester yet (ADR-0016), so live mode
    must not act differently from shadow: a person gets the proposed
    question. A clarify ticket left without a review item would be
    invisible to every queue."""
    from apps.tickets.models import IncidentVerdict

    settings.SHADOW_MODE = shadow
    ticket = make_ticket(employee_user)
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(Ticket, "classify_similarity", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(
        ai_engine, "analyze", lambda masked, request_id: _clarify_response(request_id)
    )

    result = process_ticket.apply(args=(ticket.id,)).get()

    assert result["branch"] == Branch.CLARIFY.value
    ticket.refresh_from_db()
    assert ticket.status == "pending_review"
    assert list(ticket.review_items.values_list("queue", flat=True)) == ["clarification"]
