from __future__ import annotations

from django.db.models import QuerySet
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.review.models import ReviewDecision, ReviewError, ReviewItem
from apps.review.request_schema import DecisionIn
from apps.review.response_schema import DecisionOut, ReviewItemOut
from common.permissions import AuthedRequest

router = Router(tags=["review"])


@router.get("/queue", auth=JWTAuth(), response=list[ReviewItemOut])
def list_queue(
    request: AuthedRequest, queue: str | None = None, state: str = "pending"
) -> QuerySet[ReviewItem]:
    return ReviewItem.objects.for_queue(queue=queue, state=state)


@router.get("/items/{item_id}", auth=JWTAuth(), response=ReviewItemOut)
def get_item(request: AuthedRequest, item_id: int) -> ReviewItem:
    return _get_or_404(item_id)


@router.post("/items/{item_id}/claim", auth=JWTAuth(), response=ReviewItemOut)
def claim_item(request: AuthedRequest, item_id: int) -> ReviewItem:
    item = _get_or_404(item_id)
    try:
        item.claim(request.auth)
    except ReviewError as e:
        raise HttpError(409, str(e)) from e
    return item


@router.post("/items/{item_id}/decide", auth=JWTAuth(), response=DecisionOut)
def decide_item(request: AuthedRequest, item_id: int, payload: DecisionIn) -> ReviewDecision:
    item = _get_or_404(item_id)
    try:
        return item.decide(
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


def _get_or_404(item_id: int) -> ReviewItem:
    try:
        return ReviewItem.objects.select_related("ticket", "ai_run").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e
