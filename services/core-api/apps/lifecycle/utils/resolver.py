"""Decides whether a move is allowed, by which transition, and what runs when it is taken. Pure."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from apps.lifecycle.models import Transition, Workflow, WorkflowAction, WorkflowStatus
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.vocabulary import (
    GOVERNED_TRIGGERS,
    Direction,
    FailureCode,
    Phase,
    Position,
    TransitionPolicy,
    Trigger,
)


@dataclass(frozen=True)
class Resolution:
    """How a move is taken: by `transition` in `direction`, or by none."""

    transition: Transition | None
    direction: Direction | None


@dataclass(frozen=True)
class MoveOption:
    """A status a ticket may move to now, and the transition that leads there, if any."""

    status: WorkflowStatus
    transition: Transition | None
    direction: Direction | None


@dataclass(frozen=True)
class PlannedRun:
    action: WorkflowAction
    phase: Phase


def find_transition(
    transitions: Sequence[Transition], current: WorkflowStatus, target: WorkflowStatus
) -> Resolution | None:
    """The transition that takes a ticket from `current` to `target`, if one is modelled."""
    for transition in transitions:
        direction = transition.direction_from(current.id)
        if direction is not None and transition.destination_from(current.id) == target.id:
            return Resolution(transition, direction)
    return None


def resolve(
    *,
    current: WorkflowStatus | None,
    target: WorkflowStatus,
    workflow: Workflow,
    transitions: Sequence[Transition],
    trigger: Trigger,
) -> Resolution | None:
    """How the move from `current` to `target` is taken, None when the ticket is already there."""
    if target.workflow_id != workflow.id:
        raise LifecycleError(
            422, FailureCode.STATUS_NOT_IN_WORKFLOW, f"{target.name!r} is not in {workflow.name!r}"
        )
    governed = trigger in GOVERNED_TRIGGERS
    if governed and current is not None and current.is_triage:
        raise LifecycleError(
            409, FailureCode.TICKET_IN_TRIAGE, f"the ticket is at {current.key!r}, owned by triage"
        )
    if governed and target.is_pipeline:
        raise LifecycleError(
            422,
            FailureCode.PIPELINE_STATUS_TARGET,
            f"only the triage pipeline moves a ticket into {target.key!r}",
        )
    if current is not None and current.id == target.id:
        return None
    if current is None or not governed:
        return Resolution(None, None)

    found = find_transition(transitions, current, target)
    if found is not None:
        return found
    if trigger is Trigger.FORCE or workflow.transition_policy == TransitionPolicy.OPEN.value:
        return Resolution(None, None)
    raise LifecycleError(
        422,
        FailureCode.TRANSITION_NOT_ALLOWED,
        f"no transition from {current.name!r} to {target.name!r}",
        details={
            "from": str(current.id),
            "to": str(target.id),
            "allowed": [
                str(t.destination_from(current.id))
                for t in transitions
                if t.direction_from(current.id) is not None
            ],
        },
    )


def allowed_moves(
    *,
    current: WorkflowStatus | None,
    workflow: Workflow,
    statuses: Sequence[WorkflowStatus],
    transitions: Sequence[Transition],
) -> list[MoveOption]:
    """The statuses a person may move a ticket at `current` to, in workflow order."""
    if current is not None and current.is_triage:
        return []
    options = []
    for status in statuses:
        if status.is_pipeline or (current is not None and status.id == current.id):
            continue
        found = find_transition(transitions, current, status) if current is not None else None
        if found is not None:
            options.append(MoveOption(status, found.transition, found.direction))
        elif current is None or workflow.transition_policy == TransitionPolicy.OPEN.value:
            options.append(MoveOption(status, None, None))
    return options


def plan_runs(
    transition_actions: Sequence[WorkflowAction], status_actions: Sequence[WorkflowAction]
) -> list[PlannedRun]:
    """The active actions a move runs, in execution order: before, enter, after."""

    def ordered(actions: Sequence[WorkflowAction]) -> list[WorkflowAction]:
        return sorted((a for a in actions if a.is_active), key=lambda a: (a.sort_order, str(a.id)))

    moving = ordered(transition_actions)
    before = [a for a in moving if a.position in (Position.BEFORE.value, Position.BOTH.value)]
    after = [a for a in moving if a.position in (Position.AFTER.value, Position.BOTH.value)]
    return (
        [PlannedRun(a, Phase.BEFORE) for a in before]
        + [PlannedRun(a, Phase.ENTER) for a in ordered(status_actions)]
        + [PlannedRun(a, Phase.AFTER) for a in after]
    )
