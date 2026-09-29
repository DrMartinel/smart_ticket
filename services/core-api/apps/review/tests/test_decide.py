"""
HITL decisions — spec §12.4's free-label loop. Every decision other than a
clean approve becomes an `EvalCandidate` carrying the reviewer's correction
and reason. An override without a reason is refused outright: it would be
data with no teachable case, and it would still close the item.
"""

import pytest

from apps.tickets.utils.patterns import PIILevel
from apps.review.models import EvalCandidate, ReviewAction, ReviewDecision, ReviewError, ReviewItem
from apps.tickets.utils.router import ReviewQueue

from apps.tickets.models import AiRun, Ticket

AI_DRAFT = {"proposed_intent": "auto_reply", "proposed_category": "network"}


def review_item(reporter) -> ReviewItem:
    ticket = Ticket.objects.create(
        public_id="TKT-REVIEW-001",
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )
    ai_run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="test",
        model="test",
        graph_version="test",
        trust_signals={},
        proposed_draft=AI_DRAFT,
    )
    return ReviewItem.objects.create(
        ticket=ticket, ai_run=ai_run, queue=ReviewQueue.LOW_CONFIDENCE.value
    )


def decide_as(item, reviewer, action: ReviewAction, reason: str | None):
    return item.decide(
        reviewer,
        action_taken=action.value,
        kb_verdict=None,
        category_verdict="wrong",
        corrected_category="access",
        corrected_kb_id=None,
        override_reason=reason,
        time_spent_sec=45,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_an_override_without_a_reason_is_refused_and_writes_nothing(
    employee_user, technician_user, reason
):
    item = review_item(employee_user)

    with pytest.raises(ReviewError, match="override_reason is required"):
        decide_as(item, technician_user, ReviewAction.REROUTE, reason)

    item.refresh_from_db()
    assert item.state == "pending"
    assert not ReviewDecision.objects.exists()
    assert not EvalCandidate.objects.exists()


@pytest.mark.django_db
def test_an_override_becomes_an_eval_candidate_with_the_reason(employee_user, technician_user):
    item = review_item(employee_user)

    decide_as(item, technician_user, ReviewAction.REROUTE, "this is an access request")

    candidate = EvalCandidate.objects.get(ticket=item.ticket)
    assert candidate.source == "human_override"
    assert candidate.ai_prediction == AI_DRAFT
    assert candidate.human_truth["override_reason"] == "this is an access request"
    assert candidate.human_truth["corrected_category"] == "access"
    item.refresh_from_db()
    assert item.state == "resolved"


@pytest.mark.django_db
def test_an_approval_resolves_the_item_without_an_eval_candidate(employee_user, technician_user):
    item = review_item(employee_user)

    decide_as(item, technician_user, ReviewAction.APPROVE, None)

    item.refresh_from_db()
    assert item.state == "resolved"
    assert not EvalCandidate.objects.exists()


@pytest.mark.django_db
def test_an_item_can_only_be_claimed_while_pending(employee_user, technician_user, manager_user):
    item = review_item(employee_user)
    item.claim(technician_user)

    with pytest.raises(ReviewError, match="not pending"):
        item.claim(manager_user)

    item.refresh_from_db()
    assert item.claimed_by == technician_user
