"""
Chat tickets: which routing decisions wait for the requester to ask for a
ticket, and what happens when they do.

A chat question is a ticket from the start, but a handoff to support is
only carried out once the requester asks for one. The danger is the other
direction: a decision that must reach a human (a block, an escalation, a
masking failure, a security clarification) quietly waiting on a requester
who closed the tab. Those tests fail if anything safety-related becomes
holdable.
"""

import pytest

from apps.audit.models import AuditLog
from apps.review.models import ReviewItem
from apps.tickets.models import Ticket, TicketSource
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.pipeline import (
    NotAwaitingRequester,
    release_to_support,
    ticket_process,
    waits_for_requester,
)
from apps.tickets.utils.router import Branch, ReasonCode, ReviewQueue, RoutingDecision


def _decision(branch: Branch, reason: ReasonCode, **kw) -> RoutingDecision:
    return RoutingDecision(branch=branch, reason_code=reason, **kw)


class TestWaitsForRequester:
    @pytest.mark.parametrize("shadow", [True, False])
    @pytest.mark.parametrize(
        "decision",
        [
            _decision(Branch.BLOCK, ReasonCode.INJECTION_DETECTED, alert_security=True),
            _decision(Branch.BLOCK, ReasonCode.PII_CRITICAL, alert_security=True),
            _decision(Branch.ESCALATE, ReasonCode.MASS_INCIDENT),
            _decision(
                Branch.HITL, ReasonCode.PII_MASK_FAILED, queue=ReviewQueue.MASK_FAILED, priority=1
            ),
            _decision(Branch.HITL, ReasonCode.CLARIFY_SECURITY, queue=ReviewQueue.LOW_CONFIDENCE),
        ],
        ids=["injection", "pii_critical", "mass_incident", "mask_failed", "clarify_security"],
    )
    def test_safety_decisions_never_wait(self, decision, shadow):
        """Each of these is a human looking at something that may already be
        wrong. The requester must not be able to keep it from support."""
        assert waits_for_requester(decision, shadow, PIILevel.ROUTINE) is False

    def test_live_auto_reply_is_the_answer_not_a_handoff(self):
        decision = _decision(Branch.AUTO_REPLY, ReasonCode.ALL_CHECKS_PASSED, kb_slug="kb-1")
        assert waits_for_requester(decision, False, PIILevel.ROUTINE) is False

    def test_shadow_auto_reply_waits(self):
        """Shadow mode sends nothing (spec §14 P1), the chat included: the
        requester is offered a ticket instead of the answer."""
        decision = _decision(Branch.AUTO_REPLY, ReasonCode.ALL_CHECKS_PASSED, kb_slug="kb-1")
        assert waits_for_requester(decision, True, PIILevel.ROUTINE) is True

    @pytest.mark.parametrize(
        "decision",
        [
            _decision(Branch.HITL, ReasonCode.TRUST_BELOW_AUTO, queue=ReviewQueue.LOW_CONFIDENCE),
            _decision(
                Branch.HITL, ReasonCode.AI_ENGINE_UNAVAILABLE, queue=ReviewQueue.LOW_CONFIDENCE
            ),
            _decision(Branch.AUTO_ROUTE, ReasonCode.ALL_CHECKS_PASSED),
            _decision(Branch.CLARIFY, ReasonCode.ALL_CHECKS_PASSED),
        ],
        ids=["hitl", "degraded", "auto_route", "clarify"],
    )
    def test_ordinary_handoffs_wait(self, decision):
        assert waits_for_requester(decision, True, PIILevel.ROUTINE) is True


@pytest.fixture
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@pytest.fixture
def no_celery(monkeypatch):
    """Submit enqueues the pipeline; tests run it themselves instead."""

    class Fake:
        def delay(self, ticket_id: str) -> None:
            pass

    monkeypatch.setattr("apps.tickets.tasks.process_ticket", Fake())


def _submit(user, source: TicketSource) -> Ticket:
    from apps.tickets.request_schema import TicketIn

    return Ticket.objects.submit(
        reporter=user,
        ticket_in=TicketIn(
            subject="Cannot reach the VPN", body="Since this morning the VPN times out."
        ),
        trace_id="trace-hold",
        source=source,
    )


@pytest.mark.django_db
class TestHoldAndRelease:
    """With the test ai-engine offline for analysis, every ticket is routed
    HITL as ai_engine_unavailable: an ordinary handoff."""

    def test_chat_ticket_waits_without_a_review_item(
        self, employee_user, ner_finds_nothing, no_celery
    ):
        ticket = _submit(employee_user, TicketSource.CHAT)
        assert ticket.pii_level == PIILevel.ROUTINE.value

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "awaiting_requester"
        assert not ticket.review_items.exists()
        # Decided and recorded like any ticket; only the execution waits.
        decision = ticket.routing_decisions.get()
        assert decision.reason_code == ReasonCode.AI_ENGINE_UNAVAILABLE.value
        assert ticket.held_decision is not None
        assert ticket.held_decision["reason_code"] == ReasonCode.AI_ENGINE_UNAVAILABLE.value

    def test_form_ticket_still_goes_straight_to_review(
        self, employee_user, ner_finds_nothing, no_celery
    ):
        ticket = _submit(employee_user, TicketSource.FORM)

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ticket.review_items.exists()

    def test_release_carries_out_the_recorded_decision(
        self, employee_user, ner_finds_nothing, no_celery
    ):
        """Release executes the held decision, not a fresh route() call, so
        what was recorded and what was done cannot differ."""
        ticket = _submit(employee_user, TicketSource.CHAT)
        ticket_process(str(ticket.id))

        release_to_support(ticket.id, employee_user.id, "trace-release")

        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ticket.held_decision is None
        item = ReviewItem.objects.get(ticket=ticket)
        assert item.queue == ReviewQueue.LOW_CONFIDENCE.value
        assert item.priority == 2
        assert item.ai_run == ticket.routing_decisions.get().ai_run
        assert AuditLog.objects.filter(
            ticket_id=ticket.id, event="requester_asked_for_ticket"
        ).exists()

    def test_release_happens_once(self, employee_user, ner_finds_nothing, no_celery):
        ticket = _submit(employee_user, TicketSource.CHAT)
        ticket_process(str(ticket.id))
        release_to_support(ticket.id, employee_user.id, None)

        with pytest.raises(NotAwaitingRequester):
            release_to_support(ticket.id, employee_user.id, None)
        assert ReviewItem.objects.filter(ticket=ticket).count() == 1

    def test_release_before_a_decision_is_refused(
        self, employee_user, ner_finds_nothing, no_celery
    ):
        ticket = _submit(employee_user, TicketSource.CHAT)

        with pytest.raises(NotAwaitingRequester):
            release_to_support(ticket.id, employee_user.id, None)

    def test_mask_failed_chat_ticket_goes_to_review_at_once(self, employee_user, no_celery):
        """The autouse offline ai-engine fails NER, so masking fails, and
        analysis fails too, so the run is degraded and never reaches the
        router. The ticket still reaches review whatever the requester does."""
        ticket = _submit(employee_user, TicketSource.CHAT)
        assert ticket.pii_level == PIILevel.MASK_FAILED.value

        ticket_process(str(ticket.id))

        ticket.refresh_from_db()
        assert ticket.status == "pending_review"
        assert ticket.held_decision is None
        assert ReviewItem.objects.filter(ticket=ticket).exists()
