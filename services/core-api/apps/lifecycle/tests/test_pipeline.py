"""The triage pipeline's status writes all go through the lifecycle, and no workflow can stop them."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.utils import timezone

from apps.lifecycle.models import Workflow
from apps.lifecycle.request_schema import FieldIn, RuleIn, TransitionPatch
from apps.lifecycle.tests.conftest import put_in
from apps.lifecycle.utils.actions import HANDLERS
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.rules import FieldType, RuleCode
from apps.lifecycle.utils.vocabulary import ActionCode, Trigger
from apps.tickets.models import Ticket
from apps.tickets.request_schema import TicketIn
from apps.tickets.tasks import process_ticket, reopen_ticket

_APPS = Path(__file__).resolve().parents[2]
# The one writer of `Ticket.status`, and the migration that adopts old tickets.
_ALLOWED = {_APPS / "tickets" / "models.py"}


class _StatusWrites(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: list[int] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == "status":
                if isinstance(target.value, ast.Name) and "ticket" in target.value.id:
                    self.found.append(node.lineno)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg == "update_fields" and "'status'" in ast.dump(node.value):
            self.found.append(node.value.lineno)
        self.generic_visit(node)


def _sources() -> list[Path]:
    return sorted(
        p
        for p in _APPS.rglob("*.py")
        if "tests" not in p.parts and "migrations" not in p.parts and "lifecycle" not in p.parts
    )


@pytest.mark.parametrize("path", _sources(), ids=lambda p: str(p.relative_to(_APPS)))
def test_pipeline_statuses_are_written_only_by_the_lifecycle(path):
    """Checks that no module outside the lifecycle assigns or saves a ticket's `status`."""

    if path in _ALLOWED:
        return
    visitor = _StatusWrites()
    visitor.visit(ast.parse(path.read_text()))

    assert visitor.found == [], f"{path.name} writes ticket.status at lines {visitor.found}"


def test_the_scan_sees_a_status_write():
    visitor = _StatusWrites()
    visitor.visit(ast.parse('ticket.status = "x"\nticket.save(update_fields=["status"])'))

    assert len(visitor.found) == 2


def test_every_action_code_has_a_handler():
    assert set(HANDLERS) == set(ActionCode)


@pytest.mark.django_db
def test_a_submitted_ticket_enters_the_default_workflow(monkeypatch, employee_user):
    monkeypatch.setattr("apps.tickets.tasks.process_ticket.delay", lambda ticket_id: None)

    ticket = Ticket.objects.submit(
        reporter=employee_user,
        ticket_in=TicketIn(subject="VPN keeps dropping", body="It drops every hour since Monday."),
        trace_id=None,
    )

    ticket = Ticket.objects.select_related("workflow_status__workflow").get(pk=ticket.pk)
    assert ticket.workflow_status is not None
    assert ticket.workflow_status.key == "new"
    assert ticket.workflow_status.workflow == Workflow.objects.default()
    assert ticket.transfers.get().trigger == Trigger.CREATE.value


@pytest.mark.django_db
def test_a_degraded_run_reaches_pending_review_through_the_lifecycle(employee_user):
    from apps.lifecycle.utils.engine import lifecycle

    ticket = Ticket.objects.create(
        public_id="TKT-LC-PIPE-1",
        reporter=employee_user,
        subject_masked="Printer offline",
        body_masked="The 3rd floor printer is offline.",
        pii_level="routine",
    )
    lifecycle.start(ticket)

    process_ticket.apply(args=(str(ticket.id),)).get()

    ticket = Ticket.objects.select_related("workflow_status").get(pk=ticket.pk)
    assert ticket.status == "pending_review"
    assert ticket.workflow_status is not None and ticket.workflow_status.key == "pending_review"
    assert ticket.transfers.latest("created_at").trigger == Trigger.SYSTEM.value


@pytest.mark.django_db
def test_a_workflows_rules_never_stop_a_reopen(ticket, strict):
    field = workflow_config.add_field(
        strict.workflow, FieldIn(name="Gate", field_type=FieldType.TEXT)
    )
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(rules=[RuleIn(field_id=field.id, rule=RuleCode.REQUIRED)]),
    )
    put_in(ticket, strict.done)
    Ticket.objects.filter(pk=ticket.pk).update(resolved_at=timezone.now(), resolution_seq=1)

    reopen_ticket.apply(args=(str(ticket.id),)).get()

    ticket = Ticket.objects.get(pk=ticket.pk)
    assert ticket.status == "reopened"
    assert ticket.reopened_count == 1
    assert ticket.resolved_at is None
