"""
HITL decisions — spec §12.4's free-label loop. Every decision other than a
clean approve becomes an `EvalCandidate` carrying the reviewer's correction
and reason. An override without a reason is refused outright: it would be
data with no teachable case, and it would still close the item.
"""

from typing import Any

import pytest

from apps.audit.models import AuditLog
from apps.categories.domain.vocabulary import CategoryError, CategoryRefusal
from apps.tickets.domain.patterns import PIILevel
from apps.review.models import (
    SECURITY_QUEUES,
    EvalCandidate,
    ReviewAction,
    ReviewDecision,
    ReviewError,
    ReviewItem,
)
from apps.teams.models import Team
from apps.tickets.domain.router import ReviewQueue
from apps.review.request_schema import DecisionIn
from apps.review.services.decisions import review_decisions

from apps.tickets.models import AiRun, Ticket

AI_DRAFT = {"proposed_intent": "auto_reply", "proposed_category": "network"}
SHOWN_ACCESS = {"classification": {"category_choice": "access", "category_confidence": 0.5}}
SHOWN_NONE = {"classification": {"category_choice": None, "category_confidence": 0.0}}


def review_item(
    reporter,
    *,
    trust_signals: dict[str, Any] | None = None,
    queue: str = ReviewQueue.LOW_CONFIDENCE.value,
    category: str | None = None,
) -> ReviewItem:
    ticket = Ticket.objects.create(
        public_id="TKT-REVIEW-001",
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
        category=category,
    )
    ai_run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="test",
        model="test",
        graph_version="test",
        trust_signals=trust_signals or {},
        proposed_draft=AI_DRAFT,
    )
    return ReviewItem.objects.create(ticket=ticket, ai_run=ai_run, queue=queue)


def confirm(item, reviewer) -> Ticket:
    """Approves `item` with the shown category marked correct and returns the ticket after."""
    review_decisions.decide(
        item,
        reviewer,
        DecisionIn(
            action_taken=ReviewAction.APPROVE.value, category_verdict="correct", time_spent_sec=10
        ),
    )
    return Ticket.objects.get(pk=item.ticket_id)


def decide_as(
    item, reviewer, action: ReviewAction, reason: str | None, corrected: str | None = "access"
):
    return review_decisions.decide(
        item,
        reviewer,
        DecisionIn(
            action_taken=action.value,
            category_verdict="wrong" if corrected else None,
            corrected_category=corrected,
            override_reason=reason,
            time_spent_sec=45,
        ),
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
@pytest.mark.parametrize("corrected", ["billing", ""])
def test_a_correction_to_an_unknown_category_is_refused_and_writes_nothing(
    employee_user, technician_user, corrected
):
    item = review_item(employee_user)

    with pytest.raises(CategoryError) as refused:
        review_decisions.decide(
            item,
            technician_user,
            DecisionIn(
                action_taken=ReviewAction.REROUTE.value,
                category_verdict="wrong",
                corrected_category=corrected,
                override_reason="wrong category",
                time_spent_sec=45,
            ),
        )

    assert refused.value.code is CategoryRefusal.UNKNOWN_CATEGORY
    item.refresh_from_db()
    assert item.state == "pending"
    assert not ReviewDecision.objects.exists()


@pytest.mark.django_db
def test_an_override_becomes_an_eval_candidate_with_the_reason(employee_user, technician_user):
    item = review_item(employee_user)

    decide_as(item, technician_user, ReviewAction.ESCALATE, "this is an access request")

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

    decide_as(item, technician_user, ReviewAction.APPROVE, None, corrected=None)

    item.refresh_from_db()
    assert item.state == "resolved"
    assert not EvalCandidate.objects.exists()


@pytest.mark.django_db
def test_a_confirmed_category_is_saved_on_a_ticket_with_none(employee_user, technician_user):
    item = review_item(employee_user, trust_signals=SHOWN_ACCESS)

    ticket = confirm(item, technician_user)

    assert (ticket.category, ticket.assigned_team) == ("access", "access")
    assert not EvalCandidate.objects.exists()


@pytest.mark.django_db
def test_a_confirmed_verdict_never_overwrites_the_tickets_category(employee_user, technician_user):
    item = review_item(employee_user, trust_signals=SHOWN_ACCESS, category="network")

    ticket = confirm(item, technician_user)

    assert (ticket.category, ticket.assigned_team) == ("network", "network")


@pytest.mark.django_db
@pytest.mark.parametrize("with_run", [False, True], ids=["no_run", "no_category_choice"])
def test_a_confirmation_with_no_category_shown_saves_none_and_goes_to_the_fallback_team(
    employee_user, technician_user, with_run
):
    item = review_item(employee_user, trust_signals=SHOWN_NONE)
    if not with_run:
        item.ai_run = None
        item.save(update_fields=["ai_run"])

    ticket = confirm(item, technician_user)

    assert ticket.category is None
    assert ticket.team == Team.objects.get(is_fallback=True)
    assert AuditLog.objects.get(event="assignment_failed").payload["reason"] == "no_category"


@pytest.mark.django_db
@pytest.mark.parametrize("queue", sorted(SECURITY_QUEUES))
def test_a_security_queue_confirmation_saves_no_category(employee_user, technician_user, queue):
    item = review_item(employee_user, trust_signals=SHOWN_ACCESS, queue=queue)

    ticket = confirm(item, technician_user)

    assert ticket.category is None
    assert ticket.team is None


@pytest.mark.django_db
def test_an_item_can_only_be_claimed_while_pending(employee_user, technician_user, manager_user):
    item = review_item(employee_user)
    item.claim(technician_user)

    with pytest.raises(ReviewError, match="not pending"):
        item.claim(manager_user)

    item.refresh_from_db()
    assert item.claimed_by == technician_user
