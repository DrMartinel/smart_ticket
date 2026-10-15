"""Which moves are allowed, by which transition, and in what order their actions run. No database."""

import uuid

import pytest

from apps.lifecycle.models import Transition, Workflow, WorkflowAction, WorkflowStatus
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.resolver import allowed_moves, plan_runs, resolve
from apps.lifecycle.utils.vocabulary import (
    Direction,
    FailureCode,
    Phase,
    TransitionPolicy,
    Trigger,
)

WF = Workflow(id=uuid.uuid4(), name="Support", transition_policy=TransitionPolicy.STRICT.value)


def status(key: str, workflow: Workflow = WF) -> WorkflowStatus:
    return WorkflowStatus(id=uuid.uuid4(), workflow_id=workflow.id, key=key, name=key.title())


NEW = status("new")
REVIEW = status("pending_review")
WORKING = status("in_progress")
HOLD = status("on_hold")
DONE = status("resolved")


def link(a: WorkflowStatus, b: WorkflowStatus, *, both: bool = False) -> Transition:
    return Transition(
        id=uuid.uuid4(),
        workflow_id=WF.id,
        from_status_id=a.id,
        to_status_id=b.id,
        name=f"{a.key}->{b.key}",
        is_bidirectional=both,
    )


TRANSITIONS = [link(REVIEW, WORKING), link(WORKING, HOLD, both=True), link(WORKING, DONE)]


def move(current, target, *, trigger=Trigger.MANUAL, workflow=WF):
    return resolve(
        current=current,
        target=target,
        workflow=workflow,
        transitions=TRANSITIONS,
        trigger=trigger,
    )


def test_a_modelled_transition_is_taken_forward():
    resolution = move(REVIEW, WORKING)

    assert resolution is not None
    assert resolution.transition is TRANSITIONS[0]
    assert resolution.direction is Direction.FORWARD


def test_a_bidirectional_transition_is_taken_in_reverse():
    resolution = move(HOLD, WORKING)

    assert resolution is not None
    assert resolution.transition is TRANSITIONS[1]
    assert resolution.direction is Direction.REVERSE


def test_a_one_way_transition_is_not_taken_backwards():
    with pytest.raises(LifecycleError) as e:
        move(DONE, WORKING)

    assert e.value.code is FailureCode.TRANSITION_NOT_ALLOWED
    assert e.value.details["allowed"] == []


def test_a_strict_workflow_refuses_an_unmodelled_move_and_lists_the_allowed_ones():
    with pytest.raises(LifecycleError) as e:
        move(REVIEW, DONE)

    assert e.value.status == 422
    assert e.value.details["allowed"] == [str(WORKING.id)]


def test_an_open_workflow_allows_an_unmodelled_move_without_a_transition():
    open_wf = Workflow(id=WF.id, name="Open", transition_policy=TransitionPolicy.OPEN.value)

    resolution = move(REVIEW, DONE, workflow=open_wf)

    assert resolution is not None and resolution.transition is None


def test_force_skips_the_transition_check():
    resolution = move(REVIEW, DONE, trigger=Trigger.FORCE)

    assert resolution is not None and resolution.transition is None


def test_moving_to_the_current_status_is_nothing():
    assert move(WORKING, WORKING) is None


@pytest.mark.parametrize("trigger", [Trigger.MANUAL, Trigger.ACTION, Trigger.FORCE])
def test_nobody_but_the_pipeline_moves_a_ticket_into_a_pipeline_status(trigger):
    with pytest.raises(LifecycleError) as e:
        move(WORKING, REVIEW, trigger=trigger)

    assert e.value.code is FailureCode.PIPELINE_STATUS_TARGET


@pytest.mark.parametrize("trigger", [Trigger.MANUAL, Trigger.ACTION, Trigger.FORCE])
def test_a_ticket_in_triage_cannot_be_moved_even_by_force(trigger):
    with pytest.raises(LifecycleError) as e:
        move(NEW, WORKING, trigger=trigger)

    assert e.value.code is FailureCode.TICKET_IN_TRIAGE
    assert e.value.status == 409


def test_the_pipeline_moves_anywhere_without_a_transition():
    resolution = move(DONE, REVIEW, trigger=Trigger.SYSTEM)

    assert resolution is not None and resolution.transition is None


def test_a_status_of_another_workflow_is_refused():
    other = Workflow(id=uuid.uuid4(), name="Other")

    with pytest.raises(LifecycleError) as e:
        move(WORKING, status("done", other))

    assert e.value.code is FailureCode.STATUS_NOT_IN_WORKFLOW


def test_allowed_moves_list_only_modelled_non_pipeline_targets():
    options = allowed_moves(
        current=WORKING,
        workflow=WF,
        statuses=[NEW, REVIEW, WORKING, HOLD, DONE],
        transitions=TRANSITIONS,
    )

    assert [o.status.key for o in options] == ["on_hold", "resolved"]


def test_a_ticket_in_triage_has_no_moves():
    options = allowed_moves(
        current=NEW, workflow=WF, statuses=[NEW, WORKING], transitions=TRANSITIONS
    )

    assert options == []


def action(code: str, position: str, *, order: int = 0, active: bool = True) -> WorkflowAction:
    return WorkflowAction(
        id=uuid.uuid4(), action=code, position=position, sort_order=order, is_active=active
    )


def test_runs_are_planned_before_then_enter_then_after():
    hook = action("call_webhook", "before")
    both = action("call_webhook", "both", order=1)
    note = action("set_field", "after")
    enter = action("assign_team", "after")

    planned = plan_runs([note, both, hook], [enter])

    assert [(p.action, p.phase) for p in planned] == [
        (hook, Phase.BEFORE),
        (both, Phase.BEFORE),
        (enter, Phase.ENTER),
        (note, Phase.AFTER),
        (both, Phase.AFTER),
    ]


def test_an_inactive_action_is_not_planned():
    assert plan_runs([action("set_field", "after", active=False)], []) == []
