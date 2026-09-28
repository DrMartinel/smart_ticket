from __future__ import annotations

from typing import Any

from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from contracts.trust import TrustSignals

from apps.accounts.rbac import AuthedRequest
from apps.review.models import ReviewItem
from apps.review.selectors import review_item_list
from apps.review.services import ReviewError, claim, decide
from apps.tickets.services.trust_scorer import score as compute_trust

router = Router(tags=["review"])


class DecisionIn(Schema):
    action_taken: str
    kb_verdict: str | None = None
    category_verdict: str | None = None
    corrected_category: str | None = None
    corrected_kb_id: int | None = None
    override_reason: str | None = None
    time_spent_sec: int


def _serialize_item(item: ReviewItem) -> dict[str, Any]:
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


@router.get("/queue", auth=JWTAuth())
def list_queue(
    request: AuthedRequest, queue: str | None = None, state: str = "pending"
) -> list[dict[str, Any]]:
    return [_serialize_item(i) for i in review_item_list(queue=queue, state=state)]


@router.get("/items/{item_id}", auth=JWTAuth())
def get_item(request: AuthedRequest, item_id: int) -> dict[str, Any]:
    item = _get_or_404(item_id)
    return _serialize_item(item)


@router.post("/items/{item_id}/claim", auth=JWTAuth())
def claim_item(request: AuthedRequest, item_id: int) -> dict[str, Any]:
    item = _get_or_404(item_id)
    try:
        claim(item, request.auth)
    except ReviewError as e:
        raise HttpError(409, str(e)) from e
    return _serialize_item(item)


@router.post("/items/{item_id}/decide", auth=JWTAuth())
def decide_item(request: AuthedRequest, item_id: int, payload: DecisionIn) -> dict[str, Any]:
    item = _get_or_404(item_id)
    try:
        decision = decide(
            item,
            request.auth,
            action_taken=payload.action_taken,
            kb_verdict=payload.kb_verdict,
            category_verdict=payload.category_verdict,
            corrected_category=payload.corrected_category,
            corrected_kb_id=payload.corrected_kb_id,
            override_reason=payload.override_reason,
            time_spent_sec=payload.time_spent_sec,
        )
    except ReviewError as e:
        raise HttpError(422, str(e)) from e
    return {"id": decision.id, "action_taken": decision.action_taken}


def _get_or_404(item_id: int) -> ReviewItem:
    try:
        return ReviewItem.objects.select_related("ticket", "ai_run").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e
