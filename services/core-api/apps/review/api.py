from __future__ import annotations

from typing import Any

from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.review.models import ReviewItem
from apps.review.schemas import DecisionIn, serialize_review_item
from apps.review.selectors import review_item_list
from apps.review.services import ReviewError, claim, decide
from common.permissions import AuthedRequest

router = Router(tags=["review"])


@router.get("/queue", auth=JWTAuth())
def list_queue(
    request: AuthedRequest, queue: str | None = None, state: str = "pending"
) -> list[dict[str, Any]]:
    return [serialize_review_item(i) for i in review_item_list(queue=queue, state=state)]


@router.get("/items/{item_id}", auth=JWTAuth())
def get_item(request: AuthedRequest, item_id: int) -> dict[str, Any]:
    item = _get_or_404(item_id)
    return serialize_review_item(item)


@router.post("/items/{item_id}/claim", auth=JWTAuth())
def claim_item(request: AuthedRequest, item_id: int) -> dict[str, Any]:
    item = _get_or_404(item_id)
    try:
        claim(item, request.auth)
    except ReviewError as e:
        raise HttpError(409, str(e)) from e
    return serialize_review_item(item)


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
