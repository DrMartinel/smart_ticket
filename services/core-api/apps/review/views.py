from __future__ import annotations

import uuid

from django.db.models import QuerySet
from ninja import Router
from ninja.errors import HttpError

from apps.review.models import ReviewDecision, ReviewError, ReviewItem
from apps.review.request_schema import CommentDecisionIn, DecisionIn
from apps.review.response_schema import DecisionOut, ReviewItemOut
from apps.review.utils import review_decisions
from apps.accounts.permissions import (
    TECHNICIAN_OR_MANAGER,
    STAFF,
    AuthedRequest,
    SessionAuth,
    refuse_unless,
    require_role,
)
from apps.tickets.utils.comments import CommentReviewChoice, comments
from apps.tickets.utils.router import ReviewQueue

router = Router(tags=["review"])


@router.get("/queue", auth=SessionAuth(), response=list[ReviewItemOut])
@require_role(*STAFF)
def list_queue(
    request: AuthedRequest, queue: str | None = None, state: str = "pending"
) -> QuerySet[ReviewItem]:
    return ReviewItem.objects.for_queue(queue=queue, state=state)


@router.get("/items/{item_id}", auth=SessionAuth(), response=ReviewItemOut)
@require_role(*STAFF)
def get_item(request: AuthedRequest, item_id: uuid.UUID) -> ReviewItem:
    return _get_or_404(item_id)


@router.post("/items/{item_id}/claim", auth=SessionAuth(), response=ReviewItemOut)
@require_role(*STAFF)
def claim_item(request: AuthedRequest, item_id: uuid.UUID) -> ReviewItem:
    item = _get_or_404(item_id)
    try:
        item.claim(request.auth)
    except ReviewError as e:
        raise HttpError(409, str(e)) from e
    return item


@router.post("/items/{item_id}/decide", auth=SessionAuth(), response=DecisionOut)
@require_role(*STAFF)
def decide_item(request: AuthedRequest, item_id: uuid.UUID, payload: DecisionIn) -> ReviewDecision:
    item = _get_or_404(item_id)
    if item.comment_id is not None:
        raise HttpError(422, "a held comment is decided at /comment-decision")
    if item.queue == ReviewQueue.RUNBOOK_APPROVAL:
        refuse_unless(request, request.auth, TECHNICIAN_OR_MANAGER)
    try:
        return review_decisions.decide(item, request.auth, payload)
    except ReviewError as e:
        raise HttpError(422, str(e)) from e


@router.post("/items/{item_id}/comment-decision", auth=SessionAuth(), response=ReviewItemOut)
@require_role(*STAFF)
def decide_comment(
    request: AuthedRequest, item_id: uuid.UUID, payload: CommentDecisionIn
) -> ReviewItem:
    _get_or_404(item_id)
    comments.review(item_id, request.auth, CommentReviewChoice(payload.choice))
    return _get_or_404(item_id)


def _get_or_404(item_id: uuid.UUID) -> ReviewItem:
    try:
        return ReviewItem.objects.select_related("ticket", "ai_run", "comment").get(id=item_id)
    except ReviewItem.DoesNotExist as e:
        raise HttpError(404, "review item not found") from e
