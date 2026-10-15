"""Workflow configuration: what a workflow refuses to become."""

from __future__ import annotations

import pytest

from apps.lifecycle.models import SystemStatus, Workflow, WorkflowStatus
from apps.lifecycle.request_schema import (
    FieldEventIn,
    FieldIn,
    FieldRuleIn,
    RuleIn,
    StatusIn,
    StatusPatch,
    SystemStatusIn,
    TransitionIn,
    TransitionPatch,
    WorkflowIn,
    WorkflowPatch,
)
from apps.lifecycle.tests.conftest import actions, put_in, status_of
from apps.lifecycle.utils.config import workflow_config
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.rules import EventCode, FieldType, RuleCode
from apps.lifecycle.utils.vocabulary import FailureCode, PipelineStatus

pytestmark = pytest.mark.django_db


def refused(code: FailureCode):
    """Expects a `LifecycleError` with `code`."""

    class Check:
        def __enter__(self):
            return self

        def __exit__(self, kind, error, tb):
            assert isinstance(error, LifecycleError), f"expected {code}, nothing raised"
            assert error.code is code, f"expected {code}, got {error.code}: {error.message}"
            return True

    return Check()


def test_a_new_workflow_holds_every_pipeline_status(manager_user):
    workflow = workflow_config.create_workflow(WorkflowIn(name="Hardware"), actor=manager_user)

    assert set(workflow.statuses.values_list("key", flat=True)) == {s.value for s in PipelineStatus}


def test_making_a_workflow_default_unsets_the_old_default(manager_user):
    old = Workflow.objects.default()

    new = workflow_config.create_workflow(
        WorkflowIn(name="New default", is_default=True), actor=manager_user
    )

    assert Workflow.objects.default() == new
    old.refresh_from_db()
    assert not old.is_default


def test_the_default_workflow_cannot_be_deleted(manager_user):
    with refused(FailureCode.WORKFLOW_IN_USE):
        workflow_config.delete_workflow(Workflow.objects.default(), actor=manager_user)


def test_a_workflow_with_tickets_cannot_be_deleted(ticket, strict, manager_user):
    put_in(ticket, strict.working)

    with refused(FailureCode.WORKFLOW_IN_USE):
        workflow_config.delete_workflow(strict.workflow, actor=manager_user)


def test_a_new_status_gets_a_snake_case_key_that_never_shadows_a_pipeline_status(strict):
    base = strict.working.base

    first = workflow_config.add_status(
        strict.workflow, StatusIn(name="Waiting on vendor", base_id=base.id)
    )
    shadow = workflow_config.add_status(strict.workflow, StatusIn(name="New!", base_id=base.id))

    assert first.key == "waiting_on_vendor"
    assert shadow.key == "new_2"


def test_a_taken_name_is_refused_not_a_database_error(strict, manager_user):
    with refused(FailureCode.NAME_TAKEN):
        workflow_config.add_status(
            strict.workflow, StatusIn(name="Done", base_id=strict.done.base.id)
        )
    with refused(FailureCode.NAME_TAKEN):
        workflow_config.update_status(strict.hold, StatusPatch(name="Working"))
    with refused(FailureCode.NAME_TAKEN):
        workflow_config.create_workflow(WorkflowIn(name="Strict"), actor=manager_user)
    with refused(FailureCode.NAME_TAKEN):
        workflow_config.create_system_status(SystemStatusIn(name="Open", color="#000000"))


def test_a_pipeline_status_cannot_be_deleted(strict, manager_user):
    with refused(FailureCode.PIPELINE_STATUS_LOCKED):
        workflow_config.delete_status(strict.review, migrate_to=None, actor=manager_user)


def test_a_pipeline_status_runs_no_actions(strict):
    with refused(FailureCode.PIPELINE_STATUS_LOCKED):
        workflow_config.update_status(
            strict.review,
            StatusPatch(actions=actions({"action": "assign_team", "params": {"team": "x"}})),
        )


def test_a_pipeline_status_can_still_be_renamed(strict):
    workflow_config.update_status(strict.review, StatusPatch(name="Waiting for a technician"))

    assert status_of(strict.workflow, "pending_review").name == "Waiting for a technician"


def test_a_status_with_tickets_needs_somewhere_to_send_them(ticket, strict, manager_user):
    put_in(ticket, strict.hold)

    with refused(FailureCode.STATUS_IN_USE):
        workflow_config.delete_status(strict.hold, migrate_to=None, actor=manager_user)

    workflow_config.delete_status(strict.hold, migrate_to=strict.working.id, actor=manager_user)

    ticket.refresh_from_db()
    assert ticket.workflow_status == strict.working
    assert not WorkflowStatus.objects.filter(pk=strict.hold.pk).exists()


def test_tickets_cannot_be_sent_into_a_pipeline_status_on_delete(ticket, strict, manager_user):
    put_in(ticket, strict.hold)

    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.delete_status(strict.hold, migrate_to=strict.review.id, actor=manager_user)


def test_no_transition_leads_into_a_pipeline_status(strict):
    with refused(FailureCode.PIPELINE_STATUS_TARGET):
        workflow_config.add_transition(
            strict.workflow,
            TransitionIn(
                from_status_id=strict.done.id, to_status_id=strict.review.id, name="reopen"
            ),
        )


def test_a_bidirectional_transition_from_a_pipeline_status_is_refused(strict):
    with refused(FailureCode.PIPELINE_STATUS_TARGET):
        workflow_config.update_transition(
            strict.review.outgoing.get(), TransitionPatch(is_bidirectional=True)
        )


def test_a_duplicate_or_reverse_of_a_two_way_transition_is_refused(strict):
    with refused(FailureCode.TRANSITION_EXISTS):
        workflow_config.add_transition(
            strict.workflow,
            TransitionIn(
                from_status_id=strict.working.id, to_status_id=strict.done.id, name="again"
            ),
        )
    with refused(FailureCode.TRANSITION_EXISTS):
        workflow_config.add_transition(
            strict.workflow,
            TransitionIn(
                from_status_id=strict.hold.id, to_status_id=strict.working.id, name="back"
            ),
        )


def test_a_transition_across_workflows_is_refused(strict):
    other = status_of(Workflow.objects.default(), "in_progress")

    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.add_transition(
            strict.workflow,
            TransitionIn(from_status_id=strict.working.id, to_status_id=other.id, name="leak"),
        )


def test_only_a_blocking_action_runs_before_a_move(strict):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.update_transition(
            strict.working.outgoing.get(to_status=strict.done),
            TransitionPatch(
                actions=actions(
                    {"action": "assign_team", "params": {"team": "x"}, "position": "before"}
                )
            ),
        )


def test_an_approval_only_runs_before_a_move(strict):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.update_status(
            strict.done,
            StatusPatch(
                actions=actions({"action": "require_approval", "params": {"approvers": "mgr"}})
            ),
        )


def test_an_action_missing_a_required_parameter_is_refused(strict):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.update_status(
            strict.done, StatusPatch(actions=actions({"action": "set_sla"}))
        )


def test_an_action_naming_a_missing_or_pipeline_status_is_refused(strict):
    for key in ("nowhere", "auto_replied"):
        with refused(FailureCode.INVALID_CONFIG):
            workflow_config.update_status(
                strict.done,
                StatusPatch(actions=actions({"action": "move_status", "params": {"status": key}})),
            )


def test_a_templated_parameter_is_accepted_without_checking_its_value(strict):
    workflow_config.update_status(
        strict.done,
        StatusPatch(
            actions=actions(
                {"action": "assign_user", "params": {"username": "{{ticket.reporter}}"}}
            )
        ),
    )

    assert strict.done.actions.count() == 1


def test_a_rule_on_a_field_of_another_workflow_is_refused(strict):
    foreign = workflow_config.add_field(
        Workflow.objects.default(), FieldIn(name="Vendor", field_type=FieldType.TEXT)
    )

    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.update_transition(
            strict.working.outgoing.get(to_status=strict.done),
            TransitionPatch(rules=[RuleIn(field_id=foreign.id, rule=RuleCode.REQUIRED)]),
        )


def test_a_field_a_transition_checks_cannot_be_deleted(strict):
    field = workflow_config.add_field(
        strict.workflow, FieldIn(name="Note", field_type=FieldType.TEXT)
    )
    workflow_config.update_transition(
        strict.working.outgoing.get(to_status=strict.done),
        TransitionPatch(rules=[RuleIn(field_id=field.id, rule=RuleCode.REQUIRED)]),
    )

    with refused(FailureCode.FIELD_IN_USE):
        workflow_config.delete_field(field)


def test_a_select_field_needs_options_and_rules_must_fit_its_type(strict):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.add_field(
            strict.workflow, FieldIn(name="Tier", field_type=FieldType.SELECT)
        )
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.add_field(
            strict.workflow,
            FieldIn(
                name="Cost",
                field_type=FieldType.NUMBER,
                rules=[FieldRuleIn(rule=RuleCode.VALID_URL)],
            ),
        )


def test_an_event_action_must_be_able_to_run_on_an_event(strict):
    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.add_field(
            strict.workflow,
            FieldIn(
                name="Escalate",
                field_type=FieldType.CHECKBOX,
                events=[
                    FieldEventIn(
                        event=EventCode.ON_SET,
                        actions=actions(
                            {"action": "require_approval", "params": {"approvers": "m"}}
                        ),
                    )
                ],
            ),
        )


def test_a_system_status_in_use_cannot_be_deleted(strict):
    with refused(FailureCode.SYSTEM_STATUS_IN_USE):
        workflow_config.delete_system_status(strict.working.base)


def test_inserting_a_system_status_shifts_the_ones_after_it():
    before = list(SystemStatus.objects.values_list("name", flat=True))

    workflow_config.create_system_status(SystemStatusIn(name="Triage", color="#000000", order=2))

    names = list(SystemStatus.objects.values_list("name", flat=True))
    assert names == [before[0], "Triage", *before[1:]]


def test_reordering_must_list_every_status_once(strict):
    ids = [s.id for s in strict.workflow.statuses.all()]

    with refused(FailureCode.INVALID_CONFIG):
        workflow_config.reorder_statuses(strict.workflow, ids[1:])

    reordered = workflow_config.reorder_statuses(strict.workflow, list(reversed(ids)))
    assert [s.id for s in reordered] == list(reversed(ids))


def test_changing_the_default_is_a_patch_to_the_new_one(strict, manager_user):
    workflow_config.update_workflow(
        strict.workflow, WorkflowPatch(is_default=True), actor=manager_user
    )

    assert Workflow.objects.default() == strict.workflow
