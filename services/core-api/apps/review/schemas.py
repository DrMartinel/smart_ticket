"""
Request and response shapes for the HITL review endpoints.
"""

from __future__ import annotations

from typing import Any

from ninja import Schema

from contracts.trust import TrustSignals

from apps.review.models import ReviewItem
from apps.tickets.services.trust_scorer import score as compute_trust


class DecisionIn(Schema):
    action_taken: str
    kb_verdict: str | None = None
    category_verdict: str | None = None
    corrected_category: str | None = None
    corrected_kb_id: int | None = None
    override_reason: str | None = None
    time_spent_sec: int


def serialize_review_item(item: ReviewItem) -> dict[str, Any]:
    # `contributions` is deliberately NOT stored on ai_runs — it's
    # deterministically recomputable from trust_signals + the active
    # model file, so recomputing at read time avoids duplicating data
    # that could drift from the model that actually produced it. This is
    # what lets TrustSignalsPanel answer "why 0.62" on the UI, not just
    # display a bare number (spec §4.4 comment on TrustScore.contributions).
    ai_run = item.ai_run
    contributions = None
    if ai_run is not None and ai_run.trust_signals:
        trust = compute_trust(TrustSignals(**ai_run.trust_signals))
        contributions = trust.contributions

    return {
        "id": item.id,
        "ticket_public_id": item.ticket.public_id,
        "subject_masked": item.ticket.subject_masked,
        "body_masked": item.ticket.body_masked,
        "queue": item.queue,
        "priority": item.priority,
        "state": item.state,
        "claimed_by": item.claimed_by_id,
        "created_at": item.created_at.isoformat(),
        "ai_run_id": item.ai_run_id,
        "trust_signals": ai_run.trust_signals if ai_run is not None else None,
        "trust_score": float(ai_run.trust_score)
        if ai_run is not None and ai_run.trust_score is not None
        else None,
        "trust_contributions": contributions,
        "proposed_draft": ai_run.proposed_draft if ai_run is not None else None,
        "routing_decisions": [
            {
                "branch": rd.branch,
                "reason_code": rd.reason_code,
                "reason_detail": rd.reason_detail,
                "gate_failed": rd.gate_failed,
                "shadow_mode": rd.shadow_mode,
            }
            for rd in item.ticket.routing_decisions.order_by("-decided_at")[:1]
        ],
    }
