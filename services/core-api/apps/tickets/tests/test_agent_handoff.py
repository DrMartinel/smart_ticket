"""
A ticket the agent handed to a person (F15 BR-F15-14, FR-F15-017): the
router's gate sends it to HITL with the agent's reason, whatever ai-engine
proposed for it.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.incidents.utils.incidents import incidents
from apps.rollout.testing import all_live
from apps.tickets.models import IncidentVerdict, Ticket, TicketSource
from apps.tickets.tests.test_clarification import _clarify_response
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.pipeline import ticket_process, waits_for_requester
from apps.tickets.utils.router import Branch, ReasonCode, ReviewQueue, RoutingDecision
from infrastructure.ai_engine import ai_engine


@pytest.fixture
def engine_proposes_a_question(monkeypatch):
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(
        ai_engine, "analyze", lambda masked, request_id: _clarify_response(request_id)
    )


def _handed_off(reporter, reason: str | None = "agent_step_limit") -> Ticket:
    return Ticket.objects.create(
        public_id="TKT-TEST-AGENT-001",
        reporter=reporter,
        subject_masked="Reset my VPN profile",
        body_masked="Please reset my VPN profile, it keeps failing.",
        pii_level=PIILevel.ROUTINE.value,
        source=TicketSource.CHAT.value,
        agent_handoff_reason=reason,
    )


@pytest.mark.django_db
def test_a_handed_off_ticket_reaches_a_person_with_the_agents_reason(
    employee_user, engine_proposes_a_question, settings
):
    settings.SHADOW_MODE = True
    ticket = _handed_off(employee_user)

    ticket_process(str(ticket.id))

    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_step_limit")
    assert list(ticket.review_items.values_list("queue", flat=True)) == ["low_confidence"]
    assert not ticket.clarifications.exists()


@pytest.mark.django_db
def test_a_live_handoff_waits_for_the_employee(employee_user, engine_proposes_a_question, settings):
    """OQ-F15-04 (a): the employee decides whether to open the ticket."""
    all_live(settings)
    ticket = _handed_off(employee_user, "agent_tool_failed")

    ticket_process(str(ticket.id))

    ticket.refresh_from_db()
    assert ticket.status == "awaiting_requester"
    assert ticket.routing_decisions.get().reason_code == "agent_tool_failed"
    assert not ticket.clarifications.exists()


@pytest.mark.django_db
def test_an_agent_mask_failed_handoff_never_waits(
    employee_user, engine_proposes_a_question, settings
):
    """§h.4: it goes to support without waiting for the employee."""
    all_live(settings)
    ticket = _handed_off(employee_user, "agent_mask_failed")
    Ticket.objects.filter(id=ticket.id).update(pii_level=PIILevel.MASK_FAILED.value)

    ticket_process(str(ticket.id))

    ticket.refresh_from_db()
    assert ticket.status != "awaiting_requester"
    assert ticket.routing_decisions.get().reason_code == "pii_mask_failed"


def test_an_agent_mask_failed_decision_never_waits_whatever_the_pii_level():
    decision = RoutingDecision(
        branch=Branch.HITL,
        reason_code=ReasonCode.AGENT_MASK_FAILED,
        queue=ReviewQueue.LOW_CONFIDENCE,
    )
    assert waits_for_requester(decision, False, PIILevel.ROUTINE) is False


@pytest.mark.django_db
def test_a_ticket_cannot_carry_an_unknown_handoff_reason(employee_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        _handed_off(employee_user, "agent_felt_like_it")
