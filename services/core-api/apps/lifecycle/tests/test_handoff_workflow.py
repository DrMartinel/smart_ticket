"""Workflow rules at handoff: the first active matching rule chooses the workflow, by category,
the latest routing decision's branch and the priority (ADR-0055)."""

from __future__ import annotations

import pytest
from django.conf import settings

from apps.audit.models import AuditLog
from apps.categories.models import Category
from apps.lifecycle.domain.vocabulary import PipelineStatus
from apps.lifecycle.models import Workflow, WorkflowRule
from apps.lifecycle.services import engine
from apps.lifecycle.services.engine import lifecycle
from apps.lifecycle.tests.conftest import StrictFlow, make_ticket, status_of
from apps.lifecycle.tests.test_category_workflow import approve, reload, review_item, workflow_of
from apps.sla.services.clocks import initial_priority
from apps.teams.models import Team
from apps.tickets.domain.router import Branch, ReasonCode
from apps.tickets.domain.router import RoutingDecision as Decision
from apps.tickets.models import RoutingDecision, Ticket
from apps.tickets.services.pipeline import _execute_or_enqueue

pytestmark = pytest.mark.django_db


def add_rule(workflow: Workflow, *, order: int = 1, active: bool = True, **keys) -> WorkflowRule:
    return WorkflowRule.objects.create(
        order=order, workflow=workflow, is_active=active, change_reason="test", **keys
    )


def decided(ticket: Ticket, branch: Branch) -> None:
    RoutingDecision.objects.create(
        ticket=ticket,
        branch=branch.value,
        reason_code=ReasonCode.ALL_CHECKS_PASSED.value,
        reason_detail="",
        thresholds_used={},
    )


def auto_route(ticket: Ticket) -> None:
    decided(ticket, Branch.AUTO_ROUTE)
    decision = Decision(
        branch=Branch.AUTO_ROUTE, reason_code=ReasonCode.ALL_CHECKS_PASSED, category="network"
    )
    _execute_or_enqueue(ticket, None, decision, False, None)


def moved_audit(ticket: Ticket) -> dict:
    return (
        AuditLog.objects.filter(ticket_id=ticket.id, event="ticket_status_changed")
        .latest("occurred_at")
        .payload
    )


def skipped() -> list[dict]:
    return [a.payload for a in AuditLog.objects.filter(event="category_workflow_skipped")]


def test_an_auto_routed_ticket_enters_the_workflow_its_branch_rule_names(
    employee_user, strict: StrictFlow
):
    rule = add_rule(strict.workflow, branch=Branch.AUTO_ROUTE.value)
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)

    auto_route(ticket)

    assert reload(ticket).workflow_status == status_of(strict.workflow, "auto_routed")
    payload = moved_audit(ticket)
    assert (payload["selected_by"], payload["branch"]) == (str(rule.id), "auto_route")


def test_a_reviewed_ticket_enters_the_workflow_its_branch_rule_names(
    employee_user, technician_user, strict: StrictFlow
):
    add_rule(strict.workflow, branch=Branch.AUTO_ROUTE.value)
    reviewed = add_rule(strict.workflow, order=2, branch=Branch.HITL.value)
    ticket = make_ticket(employee_user)
    decided(ticket, Branch.HITL)

    approve(review_item(ticket), technician_user, category_verdict="correct")

    assert reload(ticket).workflow_status == status_of(strict.workflow, "pending_review")
    assert moved_audit(ticket)["selected_by"] == str(reviewed.id)


def test_the_priority_the_clocks_set_at_handoff_is_the_one_matched(
    employee_user, strict: StrictFlow
):
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)
    assert reload(ticket).priority is None
    Ticket.objects.filter(pk=ticket.pk).update(category="network")
    starting = initial_priority(reload(ticket), settings.THRESHOLDS.sla).priority
    rule = add_rule(strict.workflow, category_id="network", priority=starting.value)

    auto_route(reload(ticket))

    assert reload(ticket).priority == starting.value
    assert workflow_of(ticket) == strict.workflow
    assert moved_audit(ticket)["selected_by"] == str(rule.id)


def test_a_rule_for_another_priority_falls_back_to_the_categorys_workflow(
    employee_user, manager_user, strict: StrictFlow
):
    other = Workflow.objects.create(name="Major")
    Category.objects.filter(slug="network").update(workflow=strict.workflow)
    add_rule(other, priority="P1")
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)
    Ticket.objects.filter(pk=ticket.pk).update(priority="P4")

    auto_route(reload(ticket))

    assert workflow_of(ticket) == strict.workflow
    assert moved_audit(ticket)["selected_by"] == "category"


def test_an_inactive_rule_chooses_nothing(employee_user, strict: StrictFlow):
    add_rule(strict.workflow, branch=Branch.AUTO_ROUTE.value, active=False)
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)

    auto_route(ticket)

    assert workflow_of(ticket) == Workflow.objects.default()


def test_a_rule_naming_the_default_keeps_a_ticket_out_of_its_categorys_workflow(
    employee_user, strict: StrictFlow
):
    Category.objects.filter(slug="network").update(workflow=strict.workflow)
    add_rule(Workflow.objects.default(), category_id="network")
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)

    auto_route(ticket)

    assert workflow_of(ticket) == Workflow.objects.default()


def test_a_rule_moves_a_ticket_with_no_category(employee_user, strict: StrictFlow):
    rule = add_rule(strict.workflow)
    ticket = make_ticket(employee_user)

    lifecycle.enter_handoff_workflow(ticket, None, actor=None)

    assert workflow_of(ticket) == strict.workflow
    payload = moved_audit(ticket)
    assert (payload["selected_by"], payload["branch"]) == (str(rule.id), None)


def test_a_failing_selection_is_skipped_audited_and_the_ticket_keeps_its_team(
    employee_user, strict: StrictFlow, monkeypatch
):
    add_rule(strict.workflow, branch=Branch.AUTO_ROUTE.value)
    ticket = make_ticket(employee_user, at=PipelineStatus.NEW)

    def boom(*a, **kw):
        raise RuntimeError("selection failed")

    monkeypatch.setattr(engine, "select_workflow", boom)

    auto_route(ticket)

    assert reload(ticket).workflow_status == status_of(Workflow.objects.default(), "auto_routed")
    assert [(p["reason"], p["error"]) for p in skipped()] == [("error", "RuntimeError")]
    team = Team.objects.owning("network")
    assert team is not None
    assert reload(ticket).team == team


def test_a_ticket_a_person_already_moved_on_is_not_moved_by_a_rule(
    employee_user, strict: StrictFlow
):
    rule = add_rule(strict.workflow)
    ticket = make_ticket(employee_user)
    lifecycle.enter_handoff_workflow(ticket, "network", actor=None)
    working = strict.working
    Ticket.objects.filter(pk=ticket.pk).update(workflow_status=working, status=working.key)
    rule.workflow = Workflow.objects.default()
    rule.save()

    lifecycle.enter_handoff_workflow(reload(ticket), "network", actor=None)

    assert reload(ticket).workflow_status == working
    [payload] = skipped()
    assert (payload["reason"], payload["selected_by"]) == ("already_moved_on", str(rule.id))
