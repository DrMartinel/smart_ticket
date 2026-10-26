"""A reviewer's decision on a review item: the label it records and, for approve or reroute, the
team and person the ticket goes to (spec §12.4, F2 UC-F2-01)."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.accounts.models import User
from apps.review.models import (
    SECURITY_QUEUES,
    EvalCandidate,
    ReviewAction,
    ReviewDecision,
    ReviewError,
    ReviewItem,
)
from apps.review.request_schema import DecisionIn
from apps.sla.utils.clocks import sla_clocks
from apps.teams.utils.assignment import assignment
from apps.teams.utils.vocabulary import AssignmentTrigger

# Decisions that hand the ticket to support; the others answer, close or escalate it.
_HANDOFF = (ReviewAction.APPROVE.value, ReviewAction.REROUTE.value)


class ReviewDecisions:
    """Records review decisions."""

    @transaction.atomic
    def decide(self, item: ReviewItem, reviewer: User, choice: DecisionIn) -> ReviewDecision:
        """Records the decision and resolves the item. Any action other than a clean approve
        becomes an `EvalCandidate` with the reviewer's correction and stated reason; one that
        changes the category is a `reroute` label (BR-F2-06). Approving a blocked ticket's item
        agrees with the block and hands nothing off (F8)."""
        action = choice.action_taken
        if action != ReviewAction.APPROVE.value and not (
            choice.override_reason and choice.override_reason.strip()
        ):
            raise ReviewError("override_reason is required when action_taken != 'approve'")

        decision = ReviewDecision.objects.create(
            review_item=item,
            reviewer=reviewer,
            kb_verdict=choice.kb_verdict,
            category_verdict=choice.category_verdict,
            corrected_category=choice.corrected_category,
            corrected_kb_id=choice.corrected_kb_id,
            action_taken=action,
            override_reason=choice.override_reason,
            time_spent_sec=choice.time_spent_sec,
        )
        item.state = "resolved"
        item.save(update_fields=["state"])
        sla_clocks.responded(item.ticket, reviewer)

        ticket = item.ticket
        before = ticket.category
        corrected = choice.corrected_category
        rerouted = action in _HANDOFF and corrected is not None and corrected != before
        if action != ReviewAction.APPROVE.value or rerouted:
            ai_run = item.ai_run
            EvalCandidate.objects.create(
                ticket=ticket,
                source="reroute" if rerouted else "human_override",
                ai_prediction={"category": before}
                if rerouted
                else ((ai_run.proposed_draft or {}) if ai_run is not None else {}),
                human_truth=self.human_truth(choice),
            )
        if action in _HANDOFF and item.queue not in SECURITY_QUEUES:
            category = self.category_for(item, choice)
            if rerouted:
                ticket.category = corrected
                ticket.save(update_fields=["category"])
            assignment.assign_after_handoff(
                ticket, AssignmentTrigger.REVIEW, category=category, actor=reviewer
            )
        return decision

    def category_for(self, item: ReviewItem, choice: DecisionIn) -> str | None:
        """The reviewer's correction, else the router's category, else the category the reviewer
        was shown and confirmed; never a proposal (BR-F2-06)."""
        if choice.corrected_category:
            return choice.corrected_category
        if item.ticket.category:
            return item.ticket.category
        if choice.category_verdict == "correct" and item.ai_run is not None:
            shown = (item.ai_run.trust_signals or {}).get("classification") or {}
            return shown.get("category_choice")
        return None

    def human_truth(self, choice: DecisionIn) -> dict[str, Any]:
        return {
            "action_taken": choice.action_taken,
            "kb_verdict": choice.kb_verdict,
            "category_verdict": choice.category_verdict,
            "corrected_category": choice.corrected_category,
            "corrected_kb_id": str(choice.corrected_kb_id) if choice.corrected_kb_id else None,
            "override_reason": choice.override_reason,
        }


# --- the review decision service ---

review_decisions = ReviewDecisions()
