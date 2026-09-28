"""HITL queue reads — spec §3.4."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.review.models import ReviewItem


def review_item_list(*, queue: str | None, state: str) -> QuerySet[ReviewItem]:
    """Most urgent first (priority 1 = blocked, escalated or mask-failed),
    then longest-waiting first within a priority."""
    qs = ReviewItem.objects.select_related("ticket", "ai_run").filter(state=state)
    if queue:
        qs = qs.filter(queue=queue)
    return qs.order_by("priority", "created_at")
