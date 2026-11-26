"""A category's workflow: the ticket moves into it at handoff (ADR-0049 part 3)."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditLog
from apps.categories.models import Category
from apps.lifecycle.domain.errors import LifecycleError
from apps.lifecycle.domain.vocabulary import PipelineStatus, Trigger
from apps.lifecycle.models import Transfer, Workflow
from apps.lifecycle.request_schema import FieldIn, StatusIn, WorkflowIn
from apps.lifecycle.services.config import workflow_config
from apps.lifecycle.services.engine import lifecycle
from apps.lifecycle.services.fields import field_values
from apps.lifecycle.domain.rules import FieldType
from apps.lifecycle.tests.conftest import StrictFlow, make_ticket, put_in, status_of
from apps.review.models import ReviewAction, ReviewItem
from apps.review.request_schema import DecisionIn
from apps.review.services.decisions import review_decisions
from apps.sla.services.clocks import sla_clocks
from apps.tickets.domain.router import Branch, ReasonCode, ReviewQueue, RoutingDecision
from apps.tickets.models import AiRun, Ticket
from apps.tickets.services.pipeline import _execute_or_enqueue

pytestmark = pytest.mark.django_db


def reload(ticket: Ticket) -> Ticket:
    return Ticket.objects.select_related("workflow_status").get(pk=ticket.pk)


def workflow_of(ticket: Ticket) -> Workflow:
    status = reload(ticket).workflow_status
    assert status is not None
    return status.workflow


def give(slug: str, workflow: Workflow | None) -> None:
    Category.objects.filter(slug=slug).update(workflow=workflow)


def skipped() -> list[dict]:
    return [a.payload for a in AuditLog.objects.filter(event="category_workflow_skipped")]


def review_item(ticket: Ticket, *, queue: ReviewQueue = ReviewQueue.LOW_CONFIDENCE) -> ReviewItem:
    ai_run = AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="test",
        model="test",
        graph_version="test",
        trust_signals={"classification": {"category_choice": "network"}},
        proposed_draft={},
    )
    return ReviewItem.objects.create(ticket=ticket, ai_run=ai_run, queue=queue.value)


def approve(item: ReviewItem, reviewer, **choice) -> None:
    review_decisions.decide(
        item,
        reviewer,
        DecisionIn(action_taken=ReviewAction.APPROVE.value, time_spent_sec=30, **choice),
    )


# ── the engine ──


def test_a_ticket_in_the_default_workflow_stays_when_its_category_names_none(employee_user):
    ticket = make_ticket(employee_user)
    before = ticket.workflow_status

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert reload(ticket).workflow_status == before
    assert skipped() == []


def test_no_category_leaves_the_ticket_in_its_workflow(employee_user, strict: StrictFlow):
    ticket = put_in(make_ticket(employee_user), strict.review)

    lifecycle.enter_category_workflow(ticket, None, actor=None)

    assert reload(ticket).workflow_status == strict.review
    assert skipped() == []


def test_a_ticket_enters_the_categorys_workflow_at_the_same_pipeline_status(
    employee_user, strict: StrictFlow
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user, at=PipelineStatus.AUTO_ROUTED)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    target = status_of(strict.workflow, "auto_routed")
    assert reload(ticket).workflow_status == target
    assert ticket.workflow_status == target, "the caller's instance is updated"
    transfer = Transfer.objects.filter(ticket=ticket).latest("committed_at")
    assert transfer.trigger == Trigger.SYSTEM.value
    audit = AuditLog.objects.filter(ticket_id=ticket.id, event="ticket_status_changed").latest(
        "occurred_at"
    )
    assert (audit.payload["workflow"], audit.payload["category"]) == ("Strict", "network")


def test_a_ticket_keeps_its_field_values_of_the_same_name_and_type(
    employee_user, strict: StrictFlow
):
    default = Workflow.objects.default()
    workflow_config.add_field(default, FieldIn(name="Vendor", field_type=FieldType.TEXT))
    workflow_config.add_field(default, FieldIn(name="Room", field_type=FieldType.TEXT))
    workflow_config.add_field(strict.workflow, FieldIn(name="Vendor", field_type=FieldType.TEXT))
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    field_values.write_by_name(ticket, {"Vendor": "Acme", "Room": "4.12"}, depth=0)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert field_values.by_name(ticket) == {"Vendor": "Acme"}
    audit = AuditLog.objects.filter(ticket_id=ticket.id, event="ticket_status_changed").latest(
        "occurred_at"
    )
    assert audit.payload["dropped_fields"] == ["Room"]


def test_a_ticket_a_person_already_moved_stays_in_its_workflow(
    employee_user, manager_user, strict: StrictFlow
):
    workflow_config.add_status(strict.workflow, StatusIn(name="Waiting on requester"))
    give("network", strict.workflow)
    waiting = status_of(Workflow.objects.default(), "waiting_on_requester")
    assert waiting.pauses_sla
    ticket = put_in(make_ticket(employee_user), waiting)

    lifecycle.enter_category_workflow(ticket, "network", actor=manager_user)

    assert reload(ticket).workflow_status == waiting
    [payload] = skipped()
    assert payload["reason"] == "already_moved_on"
    assert (payload["category"], payload["workflow"], payload["status"]) == (
        "network",
        "Strict",
        "waiting_on_requester",
    )


def test_a_failed_move_is_audited_and_leaves_the_ticket_where_it_is(
    employee_user, strict: StrictFlow, monkeypatch
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    before = ticket.workflow_status

    def boom(*a, **kw):
        raise RuntimeError("carry-over failed")

    monkeypatch.setattr(field_values, "carry_over", boom)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert reload(ticket).workflow_status == before
    assert ticket.workflow_status == before
    [payload] = skipped()
    assert (payload["reason"], payload["error"]) == ("error", "RuntimeError")


def test_a_move_that_fails_after_writing_leaves_no_part_of_it_behind(
    employee_user, strict: StrictFlow, monkeypatch
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    before = ticket.workflow_status
    moves = Transfer.objects.filter(ticket=ticket).count()

    def boom(*a, **kw):
        raise RuntimeError("clock failed")

    monkeypatch.setattr(sla_clocks, "on_status_entered", boom)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert reload(ticket).workflow_status == before
    assert Transfer.objects.filter(ticket=ticket).count() == moves
    assert [(p["reason"], p["error"]) for p in skipped()] == [("error", "RuntimeError")]


def test_an_escalated_ticket_enters_the_categorys_workflow(employee_user, strict: StrictFlow):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user, at=PipelineStatus.ESCALATED)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert reload(ticket).workflow_status == status_of(strict.workflow, "escalated")


def test_a_ticket_with_a_move_running_stays_put_and_is_audited(employee_user, strict: StrictFlow):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    Ticket.objects.filter(pk=ticket.pk).update(waiting_transform=True)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert workflow_of(ticket) == Workflow.objects.default()
    assert [p["reason"] for p in skipped()] == ["a_move_is_running"]


def test_a_ticket_already_in_the_workflow_is_not_moved_again(employee_user, strict: StrictFlow):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    lifecycle.enter_category_workflow(ticket, "network", actor=None)
    moves = Transfer.objects.filter(ticket=ticket).count()

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert Transfer.objects.filter(ticket=ticket).count() == moves
    assert skipped() == []


def test_a_workflow_that_lost_a_pipeline_status_gets_it_back(employee_user, manager_user):
    workflow = workflow_config.create_workflow(WorkflowIn(name="Lean"), actor=manager_user)
    workflow_config.add_status(workflow, StatusIn(name="Doing"))
    workflow.statuses.filter(key="pending_review").delete()
    give("network", workflow)
    ticket = make_ticket(employee_user)

    lifecycle.enter_category_workflow(ticket, "network", actor=None)

    assert reload(ticket).workflow_status == status_of(workflow, "pending_review")


def test_a_workflow_a_category_names_cannot_be_deleted(manager_user, strict: StrictFlow):
    give("network", strict.workflow)

    with pytest.raises(LifecycleError) as refused:
        workflow_config.delete_workflow(strict.workflow, actor=manager_user)

    assert refused.value.status == 409
    assert refused.value.details == {"categories": ["network"]}
    assert Workflow.objects.filter(pk=strict.workflow.pk).exists()


# ── the handoffs ──


def test_an_auto_routed_ticket_enters_its_categorys_workflow(employee_user, strict: StrictFlow):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)
    decision = RoutingDecision(
        branch=Branch.AUTO_ROUTE, reason_code=ReasonCode.ALL_CHECKS_PASSED, category="network"
    )

    _execute_or_enqueue(ticket, None, decision, False, None)

    assert reload(ticket).workflow_status == status_of(strict.workflow, "auto_routed")


def test_an_auto_routed_ticket_in_shadow_mode_stays_in_the_default_workflow(
    employee_user, strict: StrictFlow
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)
    decision = RoutingDecision(
        branch=Branch.AUTO_ROUTE, reason_code=ReasonCode.ALL_CHECKS_PASSED, category="network"
    )

    _execute_or_enqueue(ticket, None, decision, True, None)

    assert workflow_of(ticket) == Workflow.objects.default()


def test_a_reviewers_correction_moves_the_ticket_into_the_corrected_categorys_workflow(
    employee_user, technician_user, strict: StrictFlow
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    Ticket.objects.filter(pk=ticket.pk).update(category="software")

    approve(
        review_item(reload(ticket)),
        technician_user,
        category_verdict="wrong",
        corrected_category="network",
    )

    assert reload(ticket).workflow_status == status_of(strict.workflow, "pending_review")
    transfer = Transfer.objects.filter(ticket=ticket).latest("committed_at")
    assert transfer.actor == technician_user


def test_a_category_jev_chose_and_the_reviewer_confirmed_uses_its_workflow(
    employee_user, technician_user, strict: StrictFlow
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)

    approve(review_item(ticket), technician_user, category_verdict="correct")

    assert reload(ticket).workflow_status == status_of(strict.workflow, "pending_review")


def test_a_correction_to_a_category_with_no_workflow_returns_the_ticket_to_the_default(
    employee_user, technician_user, strict: StrictFlow
):
    give("network", strict.workflow)
    ticket = put_in(make_ticket(employee_user), strict.review)
    Ticket.objects.filter(pk=ticket.pk).update(category="network")

    approve(
        review_item(reload(ticket)),
        technician_user,
        category_verdict="wrong",
        corrected_category="software",
    )

    assert reload(ticket).workflow_status == status_of(Workflow.objects.default(), "pending_review")


def test_a_failed_move_never_undoes_the_reviewers_decision(
    employee_user, technician_user, strict: StrictFlow, monkeypatch
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user)
    item = review_item(ticket)

    def boom(*a, **kw):
        raise RuntimeError("carry-over failed")

    monkeypatch.setattr(field_values, "carry_over", boom)

    approve(item, technician_user, category_verdict="correct")

    item.refresh_from_db()
    assert item.state == "resolved"
    assert item.decisions.exists()
    assert workflow_of(ticket) == Workflow.objects.default()
    assert [p["reason"] for p in skipped()] == ["error"]


def test_a_failed_move_never_undoes_an_automatic_route(
    employee_user, strict: StrictFlow, monkeypatch
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)
    decision = RoutingDecision(
        branch=Branch.AUTO_ROUTE, reason_code=ReasonCode.ALL_CHECKS_PASSED, category="network"
    )

    def boom(*a, **kw):
        raise RuntimeError("carry-over failed")

    monkeypatch.setattr(field_values, "carry_over", boom)

    _execute_or_enqueue(ticket, None, decision, False, None)

    assert reload(ticket).workflow_status == status_of(Workflow.objects.default(), "auto_routed")
    assert [p["reason"] for p in skipped()] == ["error"]


def test_an_approved_security_queue_item_stays_in_the_default_workflow(
    employee_user, technician_user, strict: StrictFlow
):
    give("network", strict.workflow)
    ticket = make_ticket(employee_user, at=PipelineStatus.BLOCKED)

    approve(review_item(ticket, queue=ReviewQueue.INJECTION), technician_user)

    assert workflow_of(ticket) == Workflow.objects.default()
