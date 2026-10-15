"""Custom field writes: masking, type checks, field rules, and the events a change fires."""

from __future__ import annotations

import pytest

from apps.lifecycle.models import ActionRun, TicketFieldValue, Workflow
from apps.lifecycle.request_schema import FieldEventIn, FieldIn, FieldPatch, FieldRuleIn
from apps.lifecycle.tests.conftest import actions
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.fields import field_values
from apps.lifecycle.utils.rules import EventCode, FieldType, RuleCode
from apps.lifecycle.utils.vocabulary import FailureCode, RunState
from apps.tickets.models import PiiQuarantine, Ticket

pytestmark = pytest.mark.django_db


def add_field(name: str, field_type: FieldType, **kw):
    return workflow_config.add_field(
        Workflow.objects.default(), FieldIn(name=name, field_type=field_type, **kw)
    )


def test_free_text_a_person_types_is_masked_and_quarantined(ticket, technician_user):
    note = add_field("Contact", FieldType.TEXT)

    field_values.write(ticket.id, {note.id: "call jane.doe@example.com"}, actor=technician_user)

    stored = TicketFieldValue.objects.get(ticket=ticket, field=note).value
    assert isinstance(stored, str)
    assert "jane.doe@example.com" not in stored
    assert "[EMAIL_" in stored
    ticket = Ticket.objects.get(pk=ticket.pk)
    assert any(ph.startswith("[EMAIL_") for ph in ticket.pii_map)
    assert PiiQuarantine.objects.filter(ticket=ticket).exists()


def test_masked_placeholders_continue_the_tickets_numbering(ticket, technician_user):
    note = add_field("Contact", FieldType.TEXT)
    Ticket.objects.filter(pk=ticket.pk).update(pii_map={"[EMAIL_1]": "ref"})

    field_values.write(ticket.id, {note.id: "a@example.com"}, actor=technician_user)

    assert TicketFieldValue.objects.get(ticket=ticket, field=note).value == "[EMAIL_2]"


def test_a_value_of_the_wrong_type_is_refused(ticket, technician_user):
    cost = add_field("Cost", FieldType.NUMBER)

    with pytest.raises(LifecycleError) as e:
        field_values.write(ticket.id, {cost.id: "twelve"}, actor=technician_user)

    assert e.value.code is FailureCode.INVALID_FIELD_VALUE
    assert not TicketFieldValue.objects.filter(ticket=ticket).exists()


def test_a_field_of_another_workflow_is_refused(ticket, strict, technician_user):
    foreign = workflow_config.add_field(
        strict.workflow, FieldIn(name="X", field_type=FieldType.TEXT)
    )

    with pytest.raises(LifecycleError) as e:
        field_values.write(ticket.id, {foreign.id: "x"}, actor=technician_user)

    assert e.value.code is FailureCode.INVALID_FIELD_VALUE


def test_a_field_rule_refuses_the_write(ticket, technician_user):
    cost = add_field(
        "Cost", FieldType.NUMBER, rules=[FieldRuleIn(rule=RuleCode.MAX, params={"max": 100})]
    )

    with pytest.raises(LifecycleError) as e:
        field_values.write(ticket.id, {cost.id: 250}, actor=technician_user)

    assert e.value.code is FailureCode.RULE_VIOLATION
    assert e.value.details[0]["message"] == "Cost must be at most 100"


def test_validate_reports_violations_without_writing(ticket):
    cost = add_field(
        "Cost", FieldType.NUMBER, rules=[FieldRuleIn(rule=RuleCode.MIN, params={"min": 1})]
    )

    check = field_values.validate(Workflow.objects.default(), {cost.id: 0})

    assert not check.valid
    assert check.violations[0]["rule"] == "min"
    assert not TicketFieldValue.objects.filter(ticket=ticket).exists()


def test_an_event_runs_its_actions_when_it_fires(ticket, technician_user, celery):
    add_field(
        "Vendor case",
        FieldType.TEXT,
        events=[
            FieldEventIn(
                event=EventCode.ON_SET,
                actions=actions({"action": "assign_team", "params": {"team": "vendor-desk"}}),
            )
        ],
    )

    field_values.write_by_name(ticket, {"Vendor case": "CASE-1"}, depth=0)
    celery.drain()

    assert Ticket.objects.get(pk=ticket.pk).assigned_team == "vendor-desk"
    run = ActionRun.objects.get(ticket=ticket)
    assert run.state == RunState.SUCCEEDED.value


def test_an_event_that_does_not_fire_queues_nothing(ticket, celery):
    add_field(
        "Vendor case",
        FieldType.TEXT,
        events=[
            FieldEventIn(
                event=EventCode.ON_CLEAR,
                actions=actions({"action": "assign_team", "params": {"team": "x"}}),
            )
        ],
    )

    field_values.write_by_name(ticket, {"Vendor case": "CASE-1"}, depth=0)

    assert celery.sent == []
    assert not ActionRun.objects.filter(ticket=ticket).exists()


def test_an_event_action_can_move_the_ticket(ticket, celery):
    add_field(
        "Fixed",
        FieldType.CHECKBOX,
        events=[
            FieldEventIn(
                event=EventCode.ON_EQUALS,
                params={"value": "True"},
                actions=actions({"action": "move_status", "params": {"status": "resolved"}}),
            )
        ],
    )

    field_values.write_by_name(ticket, {"Fixed": "true"}, depth=0)
    celery.drain()

    assert Ticket.objects.get(pk=ticket.pk).status == "resolved"


def test_an_event_chain_stops_at_the_chain_depth(ticket, celery, settings):
    ping = add_field("Ping", FieldType.TEXT)
    pong = add_field("Pong", FieldType.TEXT)
    for field, other in ((ping, "Pong"), (pong, "Ping")):
        workflow_config.update_field(
            field,
            FieldPatch(
                events=[
                    FieldEventIn(
                        event=EventCode.ON_CHANGE,
                        actions=actions(
                            {"action": "set_field", "params": {"field": other, "value": "{{now}}"}}
                        ),
                    )
                ]
            ),
        )

    field_values.write_by_name(ticket, {"Ping": "start"}, depth=0)
    celery.drain()

    runs = list(ActionRun.objects.filter(ticket=ticket).order_by("created_at"))
    assert len(runs) == settings.THRESHOLDS.lifecycle.max_chain_depth + 1
    assert [r.state for r in runs[:-1]] == [RunState.SUCCEEDED.value] * (len(runs) - 1)
    assert runs[-1].error_code == FailureCode.AUTOMATION_DEPTH_EXCEEDED.value
