"""
A ticket the agent handed to a person (F15 BR-F15-14, FR-F15-017): the
router's gate sends it to HITL with the agent's reason, whatever ai-engine
proposed for it.
"""

import json

import pytest
from django.db import IntegrityError, transaction

from apps.incidents.services.incidents import incidents
from apps.rollout.domain.vocabulary import FlagBranch
from apps.rollout.testing import flags_off
from apps.tickets.models import IncidentVerdict, Ticket, TicketSource
from apps.tickets.tests.test_clarification import _clarify_response
from apps.tickets.domain.patterns import PIILevel
from apps.tickets.services.pipeline import ticket_process, waits_for_requester
from apps.tickets.domain.router import Branch, ReasonCode, ReviewQueue, RoutingDecision
from infrastructure.ai_engine import ai_engine


@pytest.fixture
def engine_proposes_a_question(monkeypatch):
    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(
        ai_engine, "analyze", lambda masked, request_id, categories: _clarify_response(request_id)
    )


def _handed_off(
    reporter, reason: str | None = "agent_step_limit", summary: str | None = None
) -> Ticket:
    return Ticket.objects.create(
        public_id="TKT-TEST-AGENT-001",
        reporter=reporter,
        subject_masked="Reset my VPN profile",
        body_masked="Please reset my VPN profile, it keeps failing.",
        pii_level=PIILevel.ROUTINE.value,
        source=TicketSource.CHAT.value,
        agent_handoff_reason=reason,
        proposed_handoff_summary=summary,
    )


SUMMARY = "Customer asks to raise vol-db-01's IOPS quota; at 100 % of quota since 09:01"


@pytest.mark.django_db
def test_handoff_summary_never_reaches_triage_or_routing(employee_user, monkeypatch):
    sent: list[str] = []

    def analyze(masked, request_id, categories):
        sent.append(masked.model_dump_json() + json.dumps([c.model_dump() for c in categories]))
        return _clarify_response(request_id)

    monkeypatch.setattr(Ticket, "store_embedding", lambda *a: None)
    monkeypatch.setattr(incidents, "classify", lambda *a: IncidentVerdict(kind="unique"))
    monkeypatch.setattr(ai_engine, "analyze", analyze)
    ticket = _handed_off(employee_user, "agent_needs_staff", SUMMARY)

    ticket_process(str(ticket.id))

    (request,) = sent
    assert SUMMARY not in request and "vol-db-01" not in request
    run = ticket.ai_runs.get()
    assert SUMMARY not in json.dumps(run.trust_signals)
    assert "proposed_handoff_summary" not in json.dumps(run.trust_signals)
    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_needs_staff")


@pytest.mark.django_db
def test_needs_staff_ticket_goes_to_hitl_with_agent_needs_staff(
    employee_user, engine_proposes_a_question
):
    ticket = _handed_off(employee_user, "agent_needs_staff", SUMMARY)

    ticket_process(str(ticket.id))

    ticket.refresh_from_db()
    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_needs_staff")
    assert list(ticket.review_items.values_list("queue", flat=True)) == ["low_confidence"]
    assert ticket.status != "awaiting_requester" and not ticket.clarifications.exists()
    assert ticket.proposed_handoff_summary == SUMMARY


@pytest.mark.django_db
def test_a_handed_off_ticket_reaches_a_person_with_the_agents_reason(
    employee_user, engine_proposes_a_question
):
    flags_off(*FlagBranch)
    ticket = _handed_off(employee_user)

    ticket_process(str(ticket.id))

    decision = ticket.routing_decisions.get()
    assert (decision.branch, decision.reason_code) == ("hitl", "agent_step_limit")
    assert list(ticket.review_items.values_list("queue", flat=True)) == ["low_confidence"]
    assert not ticket.clarifications.exists()


@pytest.mark.django_db
def test_a_live_handoff_ticket_is_never_held_for_the_employee(
    employee_user, engine_proposes_a_question
):
    """Checks that a live hand-off ticket goes to support without waiting for the employee."""
    ticket = _handed_off(employee_user, "agent_tool_failed")

    ticket_process(str(ticket.id))

    ticket.refresh_from_db()
    assert ticket.status != "awaiting_requester" and ticket.held_decision is None
    assert ticket.routing_decisions.get().reason_code == "agent_tool_failed"
    assert list(ticket.review_items.values_list("queue", flat=True)) == ["low_confidence"]
    assert not ticket.clarifications.exists()


@pytest.mark.parametrize("reason", [ReasonCode.AGENT_STEP_LIMIT, ReasonCode.AI_ENGINE_UNAVAILABLE])
def test_an_agent_handoff_ticket_never_waits_whatever_its_decision(reason):
    decision = RoutingDecision(
        branch=Branch.HITL, reason_code=reason, queue=ReviewQueue.LOW_CONFIDENCE
    )

    assert waits_for_requester(decision, False, PIILevel.ROUTINE, agent_handoff=True) is False
    assert waits_for_requester(decision, False, PIILevel.ROUTINE, agent_handoff=False) is True


@pytest.mark.django_db
def test_an_agent_mask_failed_handoff_never_waits(employee_user, engine_proposes_a_question):
    """§h.4: it goes to support without waiting for the employee."""
    ticket = _handed_off(employee_user, "agent_mask_failed")

    ticket_process(str(ticket.id))

    ticket.refresh_from_db()
    assert ticket.status != "awaiting_requester"
    assert ticket.routing_decisions.get().reason_code == "agent_mask_failed"


@pytest.mark.django_db
def test_a_mask_failed_ticket_wins_over_its_agent_handoff_reason(
    employee_user, engine_proposes_a_question
):
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
    assert waits_for_requester(decision, False, PIILevel.ROUTINE, agent_handoff=False) is False


@pytest.mark.django_db
def test_a_ticket_cannot_carry_an_unknown_handoff_reason(employee_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        _handed_off(employee_user, "agent_felt_like_it")
