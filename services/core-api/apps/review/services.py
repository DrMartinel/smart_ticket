"""
HITL queue operations. `decide()` is where the free-label loop (spec
§12.4) actually gets created: any action other than a clean "approve"
becomes an `EvalCandidate`, carrying the human's correction and — crucially
— their stated reason, without which the override is data but not a
teachable case.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.review.models import EvalCandidate, ReviewDecision, ReviewItem


class ReviewError(Exception):
    pass


@transaction.atomic
def claim(review_item: ReviewItem, actor: User) -> ReviewItem:
    if review_item.state != "pending":
        raise ReviewError(f"review item {review_item.id} is not pending (state={review_item.state})")
    review_item.state = "claimed"
    review_item.claimed_by = actor
    review_item.claimed_at = timezone.now()
    review_item.save(update_fields=["state", "claimed_by", "claimed_at"])
    return review_item


@transaction.atomic
def decide(
    review_item: ReviewItem,
    reviewer: User,
    *,
    action_taken: str,
    kb_verdict: str | None,
    category_verdict: str | None,
    corrected_category: str | None,
    corrected_kb_id: int | None,
    override_reason: str | None,
    time_spent_sec: int,
) -> ReviewDecision:
    if action_taken != "approve" and not (override_reason and override_reason.strip()):
        raise ReviewError("override_reason is required when action_taken != 'approve'")

    decision = ReviewDecision.objects.create(
        review_item=review_item,
        reviewer=reviewer,
        kb_verdict=kb_verdict,
        category_verdict=category_verdict,
        corrected_category=corrected_category,
        corrected_kb_id=corrected_kb_id,
        action_taken=action_taken,
        override_reason=override_reason,
        time_spent_sec=time_spent_sec,
    )

    review_item.state = "resolved"
    review_item.save(update_fields=["state"])

    if action_taken != "approve":
        ai_prediction = {}
        if review_item.ai_run_id:
            ai_prediction = review_item.ai_run.proposed_draft or {}
        EvalCandidate.objects.create(
            ticket=review_item.ticket,
            source="human_override",
            ai_prediction=ai_prediction,
            human_truth={
                "action_taken": action_taken,
                "kb_verdict": kb_verdict,
                "category_verdict": category_verdict,
                "corrected_category": corrected_category,
                "corrected_kb_id": corrected_kb_id,
                "override_reason": override_reason,
            },
        )

    return decision
