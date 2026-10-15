"""Creates, changes and deletes workflow configuration, refusing what would break a workflow."""

from __future__ import annotations

import functools
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F, Max, ProtectedError, Q, QuerySet
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.lifecycle.models import (
    CustomField,
    FieldEvent,
    FieldRule,
    SystemStatus,
    Transfer,
    Transition,
    TransitionRule,
    Workflow,
    WorkflowAction,
    WorkflowStatus,
)
from apps.lifecycle.request_schema import (
    ActionIn,
    FieldEventIn,
    FieldIn,
    FieldPatch,
    FieldRuleIn,
    RuleIn,
    StatusIn,
    StatusPatch,
    SystemStatusIn,
    SystemStatusPatch,
    TransitionIn,
    TransitionPatch,
    WorkflowIn,
    WorkflowPatch,
)
from apps.lifecycle.utils.actions import HANDLERS
from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.errors import LifecycleError
from apps.lifecycle.utils.rules import (
    EVENTS,
    RULES,
    FieldType,
    event_param_errors,
    rule_param_errors,
)
from apps.lifecycle.utils.templates import VARIABLES, placeholders
from apps.tickets.models import Ticket
from apps.lifecycle.utils.vocabulary import (
    COMPLETED_PIPELINE_STATUSES,
    ActionCode,
    FailureCode,
    Phase,
    PipelineStatus,
    Position,
)


def refusing_duplicates[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Runs `fn` in a transaction and turns a uniqueness race it loses into a 409."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            with transaction.atomic():
                return fn(*args, **kwargs)
        except IntegrityError as e:
            text = str(e)
            if "transition_pair" in text:
                raise LifecycleError(
                    409, FailureCode.TRANSITION_EXISTS, "a transition already covers this move"
                ) from e
            if "name" in text or "_key" in text:
                raise LifecycleError(
                    409, FailureCode.NAME_TAKEN, "that name is already taken"
                ) from e
            raise LifecycleError(
                409, FailureCode.CONFLICT, "a concurrent change conflicts; reload and retry"
            ) from e

    return wrapper


# `Ticket.status` holds a status key, so a key fits its column.
KEY_LENGTH = Ticket._meta.get_field("status").max_length or 20


def invalid(errors: list[str]) -> LifecycleError:
    return LifecycleError(422, FailureCode.INVALID_CONFIG, "; ".join(errors), details=errors)


@dataclass(frozen=True)
class Catalog:
    """Everything a workflow can be built from."""

    field_types: list[str]
    rules: list[dict[str, Any]]
    events: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    variables: dict[str, str]


class WorkflowConfig:
    """Every change to workflow configuration."""

    # ── the catalog ──

    def catalog(self) -> Catalog:
        return Catalog(
            field_types=[t.value for t in FieldType],
            rules=[
                {
                    "code": s.code.value,
                    "name": s.name,
                    "description": s.description,
                    "err_message": s.err_message,
                    "params": list(s.params),
                    "field_types": sorted(t.value for t in s.field_types),
                }
                for s in RULES.values()
            ],
            events=[
                {
                    "code": s.code.value,
                    "name": s.name,
                    "description": s.description,
                    "params": list(s.params),
                }
                for s in EVENTS.values()
            ],
            actions=[
                {
                    "code": h.code.value,
                    "name": h.name,
                    "description": h.description,
                    "blocking": h.blocking,
                    "phases": sorted(p.value for p in h.phases),
                    "params": h.config_fields(),
                }
                for h in HANDLERS.values()
            ],
            variables=VARIABLES,
        )

    # ── system statuses ──

    @refusing_duplicates
    def create_system_status(self, data: SystemStatusIn) -> SystemStatus:
        self.check_name_free(SystemStatus.objects.all(), data.name)
        order = data.order
        if order is None:
            order = (SystemStatus.objects.aggregate(m=Max("order"))["m"] or 0) + 1
        else:
            SystemStatus.objects.filter(order__gte=order).update(order=F("order") + 1)
        status = SystemStatus.objects.create(**data.dict(exclude={"order"}), order=order)
        self.renumber_system_statuses()
        status.refresh_from_db()
        return status

    @refusing_duplicates
    def update_system_status(self, status: SystemStatus, data: SystemStatusPatch) -> SystemStatus:
        changes = data.dict(exclude_unset=True, exclude_none=True)
        if changes.get("name"):
            self.check_name_free(SystemStatus.objects.exclude(pk=status.pk), changes["name"])
        completed = changes.get("is_completed", status.is_completed)
        if completed != status.is_completed:
            self.check_pipeline_completion(status.workflow_statuses.all(), completed)
        if changes.get("is_backlog", status.is_backlog) and changes.get(
            "is_completed", status.is_completed
        ):
            raise invalid(["a status cannot be both backlog and completed"])
        if "order" in changes and changes["order"] != status.order:
            SystemStatus.objects.filter(order__gte=changes["order"]).exclude(pk=status.pk).update(
                order=F("order") + 1
            )
        for name, value in changes.items():
            setattr(status, name, value)
        status.save()
        if "order" in changes:
            self.renumber_system_statuses()
            status.refresh_from_db()
        self.restamp_resolution(status.workflow_statuses.all(), completed)
        return status

    def renumber_system_statuses(self) -> None:
        """Numbers the system statuses 1..n in their current order."""
        statuses = list(SystemStatus.objects.order_by("order", "name"))
        for order, status in enumerate(statuses, start=1):
            status.order = order
        SystemStatus.objects.bulk_update(statuses, ["order"])

    def check_pipeline_completion(
        self, statuses: QuerySet[WorkflowStatus], completed: bool
    ) -> None:
        """Refuses a stage that would make a pipeline status resolved, or one resolved not."""
        wrong = [
            s.key
            for s in statuses
            if s.is_pipeline
            and completed != (s.key in {p.value for p in COMPLETED_PIPELINE_STATUSES})
        ]
        if wrong:
            raise LifecycleError(
                422,
                FailureCode.PIPELINE_STATUS_LOCKED,
                f"pipeline statuses {sorted(set(wrong))} must keep whether they count as resolved",
            )

    def restamp_resolution(self, statuses: QuerySet[WorkflowStatus], completed: bool) -> None:
        """Brings `resolved_at` in line for tickets at `statuses`, now `completed` or not."""
        tickets = Ticket.objects.filter(workflow_status__in=statuses)
        if completed:
            tickets.filter(resolved_at__isnull=True).update(resolved_at=timezone.now())
        else:
            tickets.update(resolved_at=None)

    def delete_system_status(self, status: SystemStatus) -> None:
        try:
            status.delete()
        except ProtectedError as e:
            raise LifecycleError(
                409,
                FailureCode.SYSTEM_STATUS_IN_USE,
                "workflow statuses are based on this status",
                details={"workflow_status_count": status.workflow_statuses.count()},
            ) from e

    @transaction.atomic
    def reorder_system_statuses(self, ids: Sequence[uuid.UUID]) -> list[SystemStatus]:
        statuses = {s.id: s for s in SystemStatus.objects.select_for_update()}
        if set(ids) != set(statuses) or len(ids) != len(statuses):
            raise invalid(["ids must list every system status exactly once"])
        for order, status_id in enumerate(ids, start=1):
            statuses[status_id].order = order
        SystemStatus.objects.bulk_update(statuses.values(), ["order"])
        return list(SystemStatus.objects.all())

    # ── workflows ──

    @refusing_duplicates
    def create_workflow(self, data: WorkflowIn, *, actor: User) -> Workflow:
        """Creates a workflow holding a copy of the default workflow's pipeline statuses."""
        template = list(
            WorkflowStatus.objects.filter(
                workflow__is_default=True, key__in=[s.value for s in PipelineStatus]
            )
        )
        self.check_name_free(Workflow.objects.all(), data.name)
        if data.is_default:
            Workflow.objects.filter(is_default=True).update(is_default=False)
        workflow = Workflow.objects.create(
            name=data.name,
            description=data.description,
            transition_policy=data.transition_policy.value,
            is_default=data.is_default,
        )
        WorkflowStatus.objects.bulk_create(
            WorkflowStatus(
                workflow=workflow,
                base_id=s.base_id,
                key=s.key,
                name=s.name,
                color=s.color,
                order=s.order,
                coordinates=s.coordinates,
            )
            for s in template
        )
        for status in PipelineStatus:
            lifecycle.pipeline_status(workflow, status)
        self.audit("workflow_created", workflow, actor)
        return workflow

    @refusing_duplicates
    def update_workflow(self, workflow: Workflow, data: WorkflowPatch, *, actor: User) -> Workflow:
        changes = data.dict(exclude_unset=True, exclude_none=True)
        if "name" in changes and changes["name"] != workflow.name:
            self.check_name_free(Workflow.objects.exclude(pk=workflow.pk), changes["name"])
            self.check_unreferenced(
                self.actions_naming_workflow(workflow), FailureCode.WORKFLOW_IN_USE, "renamed"
            )
        if changes.get("is_default"):
            Workflow.objects.filter(is_default=True).exclude(pk=workflow.pk).update(
                is_default=False
            )
        if "transition_policy" in changes:
            changes["transition_policy"] = changes["transition_policy"].value
        for name, value in changes.items():
            setattr(workflow, name, value)
        workflow.save()
        self.audit("workflow_updated", workflow, actor, changes=sorted(changes))
        return workflow

    def delete_workflow(self, workflow: Workflow, *, actor: User) -> None:
        if workflow.is_default:
            raise LifecycleError(409, FailureCode.WORKFLOW_IN_USE, "the default workflow stays")
        count = Ticket.objects.filter(workflow_status__workflow=workflow).count()
        if count:
            raise LifecycleError(
                409,
                FailureCode.WORKFLOW_IN_USE,
                "tickets are in this workflow",
                details={"ticket_count": count},
            )
        self.check_unreferenced(
            self.actions_naming_workflow(workflow), FailureCode.WORKFLOW_IN_USE, "deleted"
        )
        self.audit("workflow_deleted", workflow, actor)
        workflow.delete()

    # ── statuses ──

    @refusing_duplicates
    def add_status(self, workflow: Workflow, data: StatusIn) -> WorkflowStatus:
        base = self.system_status(data.base_id)
        self.check_name_free(workflow.statuses.all(), data.name)
        self.check_actions(data.actions, workflow, owner="status")
        status = WorkflowStatus.objects.create(
            workflow=workflow,
            base=base,
            key=self.new_key(workflow, data.name),
            name=data.name,
            color=data.color or base.color,
            order=(workflow.statuses.aggregate(m=Max("order"))["m"] or 0) + 1,
            coordinates=data.coordinates,
        )
        self.replace_actions(status.actions, data.actions, status=status)
        return status

    @refusing_duplicates
    def update_status(self, status: WorkflowStatus, data: StatusPatch) -> WorkflowStatus:
        changes = data.dict(exclude_unset=True, exclude={"actions"})
        if changes.get("name"):
            self.check_name_free(status.workflow.statuses.exclude(pk=status.pk), changes["name"])
        if "base_id" in changes:
            base = self.system_status(changes.pop("base_id"))
            if base.is_completed != status.base.is_completed:
                self.check_pipeline_completion(
                    WorkflowStatus.objects.filter(pk=status.pk), base.is_completed
                )
                status.base = base
                status.save(update_fields=["base"])
                self.restamp_resolution(
                    WorkflowStatus.objects.filter(pk=status.pk), base.is_completed
                )
            status.base = base
        for name, value in changes.items():
            if value is not None:
                setattr(status, name, value)
        status.save()
        if data.actions is not None:
            if status.is_pipeline and data.actions:
                raise LifecycleError(
                    422,
                    FailureCode.PIPELINE_STATUS_LOCKED,
                    "only the triage pipeline enters this status, so it runs no actions",
                )
            self.check_actions(data.actions, status.workflow, owner="status")
            self.replace_actions(status.actions, data.actions, status=status)
        return status

    def delete_status(
        self, status: WorkflowStatus, *, migrate_to: uuid.UUID | None, actor: User
    ) -> None:
        if status.is_pipeline:
            raise LifecycleError(
                409, FailureCode.PIPELINE_STATUS_LOCKED, "the triage pipeline needs this status"
            )
        if (
            Transfer.objects.open()
            .filter(Q(before_status=status) | Q(after_status=status))
            .exists()
        ):
            raise LifecycleError(
                409, FailureCode.TICKET_TRANSFORMING, "a ticket here is mid-move; retry shortly"
            )
        self.check_unreferenced(
            self.actions_naming_status(status), FailureCode.STATUS_IN_USE, "deleted"
        )
        target = None
        if migrate_to is not None:
            target = WorkflowStatus.objects.filter(pk=migrate_to, workflow=status.workflow).first()
            if target is None or target.is_pipeline or target.id == status.id:
                raise invalid(["migrate_to must be another non-pipeline status of this workflow"])
        count = status.tickets.count()
        if count and target is None:
            raise LifecycleError(
                409,
                FailureCode.STATUS_IN_USE,
                "tickets are in this status: pass migrate_to",
                details={"ticket_count": count},
            )
        if count and target is not None:
            lifecycle.evacuate(status, target, actor=actor)
        with transaction.atomic():
            AuditLog.objects.record(
                "workflow_status_deleted",
                actor_type="human",
                actor_id=actor.id,
                payload={"workflow": str(status.workflow_id), "status": status.key},
            )
            status.delete()

    @transaction.atomic
    def reorder_statuses(
        self, workflow: Workflow, ids: Sequence[uuid.UUID]
    ) -> list[WorkflowStatus]:
        statuses = {s.id: s for s in workflow.statuses.select_for_update()}
        if set(ids) != set(statuses) or len(ids) != len(statuses):
            raise invalid(["ids must list every status of the workflow exactly once"])
        for order, status_id in enumerate(ids, start=1):
            statuses[status_id].order = order
        WorkflowStatus.objects.bulk_update(statuses.values(), ["order"])
        return list(workflow.statuses.select_related("base").prefetch_related("actions"))

    def set_position(self, status: WorkflowStatus, x: float, y: float) -> WorkflowStatus:
        status.coordinates = f"{round(x)}|{round(y)}"
        status.save(update_fields=["coordinates", "updated_at"])
        return status

    def new_key(self, workflow: Workflow, name: str) -> str:
        """A key for a new status: its name in snake case, unique in the workflow, never a
        pipeline status's."""
        folded = name.replace("đ", "d").replace("Đ", "D")
        stem = re.sub(r"[^a-z0-9]+", "_", slugify(folded).lower()).strip("_") or "status"
        taken = set(workflow.statuses.values_list("key", flat=True)) | {
            s.value for s in PipelineStatus
        }
        key, n = stem[:KEY_LENGTH], 1
        while key in taken:
            n += 1
            suffix = f"_{n}"
            key = stem[: KEY_LENGTH - len(suffix)] + suffix
        return key

    # ── transitions ──

    @refusing_duplicates
    def add_transition(self, workflow: Workflow, data: TransitionIn) -> Transition:
        start = workflow.statuses.filter(pk=data.from_status_id).first()
        end = workflow.statuses.filter(pk=data.to_status_id).first()
        if start is None or end is None:
            raise invalid(["both statuses must belong to this workflow"])
        self.check_ends(start, end, data.is_bidirectional)
        self.check_unique(workflow, start, end, data.is_bidirectional, exclude=None)
        self.check_rules(data.rules, workflow)
        self.check_actions(data.actions, workflow, owner="transition")
        transition = Transition.objects.create(
            workflow=workflow,
            from_status=start,
            to_status=end,
            name=data.name,
            point_start=data.point_start,
            point_end=data.point_end,
            is_bidirectional=data.is_bidirectional,
        )
        self.replace_rules(transition, data.rules)
        self.replace_actions(transition.actions, data.actions, transition=transition)
        return transition

    @refusing_duplicates
    def update_transition(self, transition: Transition, data: TransitionPatch) -> Transition:
        changes = data.dict(exclude_unset=True, exclude={"rules", "actions"})
        bidirectional = changes.get("is_bidirectional", transition.is_bidirectional)
        if bidirectional is None:
            bidirectional = transition.is_bidirectional
        self.check_ends(transition.from_status, transition.to_status, bidirectional)
        self.check_unique(
            transition.workflow,
            transition.from_status,
            transition.to_status,
            bidirectional,
            exclude=transition.id,
        )
        for name, value in changes.items():
            if value is not None:
                setattr(transition, name, value)
        transition.save()
        if data.rules is not None:
            self.check_rules(data.rules, transition.workflow)
            self.replace_rules(transition, data.rules)
        if data.actions is not None:
            self.check_actions(data.actions, transition.workflow, owner="transition")
            self.replace_actions(transition.actions, data.actions, transition=transition)
        return transition

    def check_ends(self, start: WorkflowStatus, end: WorkflowStatus, bidirectional: bool) -> None:
        """Refuses a transition into a pipeline status, either way it can be taken."""
        if end.is_pipeline or (bidirectional and start.is_pipeline):
            raise LifecycleError(
                422,
                FailureCode.PIPELINE_STATUS_TARGET,
                "no transition may lead into a status only the triage pipeline enters",
            )

    def check_unique(
        self,
        workflow: Workflow,
        start: WorkflowStatus,
        end: WorkflowStatus,
        bidirectional: bool,
        *,
        exclude: uuid.UUID | None,
    ) -> None:
        others = workflow.transitions.exclude(pk=exclude) if exclude else workflow.transitions.all()
        same = others.filter(from_status=start, to_status=end).exists()
        reverse = others.filter(from_status=end, to_status=start).first()
        if same or (reverse is not None and (bidirectional or reverse.is_bidirectional)):
            raise LifecycleError(
                409, FailureCode.TRANSITION_EXISTS, "a transition already covers this move"
            )

    def check_rules(self, rules: Sequence[RuleIn], workflow: Workflow) -> None:
        fields = {f.id: f for f in workflow.fields.all()}
        errors = []
        for rule in rules:
            field = fields.get(rule.field_id)
            if field is None:
                errors.append(f"field {rule.field_id} is not in this workflow")
            else:
                errors += rule_param_errors(rule.rule, FieldType(field.field_type), rule.params)
        if errors:
            raise invalid(errors)

    def replace_rules(self, transition: Transition, rules: Sequence[RuleIn]) -> None:
        transition.rules.all().delete()
        TransitionRule.objects.bulk_create(
            TransitionRule(
                transition=transition,
                field_id=r.field_id,
                rule=r.rule.value,
                params=r.params,
                is_active=r.is_active,
            )
            for r in rules
        )

    # ── custom fields ──

    @refusing_duplicates
    def add_field(self, workflow: Workflow, data: FieldIn) -> CustomField:
        self.check_name_free(workflow.fields.all(), data.name)
        self.check_field(workflow, data.field_type, data.options, data.rules, data.events)
        field = CustomField.objects.create(
            workflow=workflow,
            name=data.name,
            field_type=data.field_type.value,
            options=data.options,
            order=data.order,
        )
        self.replace_field_rules(field, data.rules)
        self.replace_events(field, data.events)
        return field

    @refusing_duplicates
    def update_field(self, field: CustomField, data: FieldPatch) -> CustomField:
        options = data.options if data.options is not None else list(field.options)
        self.check_field(
            field.workflow,
            FieldType(field.field_type),
            options,
            data.rules or [],
            data.events or [],
        )
        if data.name is not None and data.name != field.name:
            self.check_name_free(field.workflow.fields.exclude(pk=field.pk), data.name)
            self.check_unreferenced(
                self.actions_naming_field(field), FailureCode.FIELD_IN_USE, "renamed"
            )
            field.name = data.name
        if data.order is not None:
            field.order = data.order
        field.options = options
        field.save()
        if data.rules is not None:
            self.replace_field_rules(field, data.rules)
        if data.events is not None:
            self.replace_events(field, data.events)
        return field

    def delete_field(self, field: CustomField) -> None:
        self.check_unreferenced(
            self.actions_naming_field(field), FailureCode.FIELD_IN_USE, "deleted"
        )
        gates = TransitionRule.objects.filter(field=field).count()
        if gates:
            raise LifecycleError(
                409,
                FailureCode.FIELD_IN_USE,
                "transition rules check this field: remove them first",
                details={"transition_rule_count": gates},
            )
        field.delete()

    def check_field(
        self,
        workflow: Workflow,
        field_type: FieldType,
        options: Sequence[str],
        rules: Sequence[FieldRuleIn],
        events: Sequence[FieldEventIn],
    ) -> None:
        errors = []
        if field_type is FieldType.SELECT and not options:
            errors.append("a select field needs options")
        for rule in rules:
            errors += rule_param_errors(rule.rule, field_type, rule.params)
        for event in events:
            errors += event_param_errors(event.event, event.params)
            errors += self.action_errors(event.actions, workflow, owner="event")
        if errors:
            raise invalid(errors)

    def replace_field_rules(self, field: CustomField, rules: Sequence[FieldRuleIn]) -> None:
        field.rules.all().delete()
        FieldRule.objects.bulk_create(
            FieldRule(field=field, rule=r.rule.value, params=r.params, is_active=r.is_active)
            for r in rules
        )

    def replace_events(self, field: CustomField, events: Sequence[FieldEventIn]) -> None:
        field.events.all().delete()
        for e in events:
            event = FieldEvent.objects.create(
                field=field, event=e.event.value, params=e.params, is_active=e.is_active
            )
            self.replace_actions(event.actions, e.actions, field_event=event)

    # ── actions ──

    def check_actions(self, actions: Sequence[ActionIn], workflow: Workflow, *, owner: str) -> None:
        errors = self.action_errors(actions, workflow, owner=owner)
        if errors:
            raise invalid(errors)

    def action_errors(
        self, actions: Sequence[ActionIn], workflow: Workflow, *, owner: str
    ) -> list[str]:
        """What is wrong with `actions` configured on a status, transition or event."""
        errors = []
        for action in actions:
            handler = HANDLERS[action.action]
            phases = {
                "status": {Phase.ENTER},
                "event": {Phase.EVENT},
                "transition": {
                    Position.BEFORE: {Phase.BEFORE},
                    Position.AFTER: {Phase.AFTER},
                    Position.BOTH: {Phase.BEFORE, Phase.AFTER},
                }[action.position],
            }[owner]
            for phase in phases - handler.phases:
                errors.append(f"{action.action.value} cannot run in phase {phase.value!r}")
            if Phase.BEFORE in phases and not handler.blocking:
                errors.append(f"{action.action.value} is not blocking, so it cannot run before")
            errors += [
                f"{action.action.value}: {e}"
                for e in handler.config_errors(action.params, workflow)
            ]
        return errors

    def replace_actions(self, manager: Any, actions: Sequence[ActionIn], **owner: Any) -> None:
        manager.all().delete()
        WorkflowAction.objects.bulk_create(
            WorkflowAction(
                **owner,
                action=a.action.value,
                params=a.params,
                position=a.position.value,
                is_active=a.is_active,
                sort_order=i,
            )
            for i, a in enumerate(actions)
        )

    def check_name_free(self, others: QuerySet[Any], name: str) -> None:
        """Refuses `name` when one of `others` already has it."""
        if others.filter(name__iexact=name.strip()).exists():
            raise LifecycleError(409, FailureCode.NAME_TAKEN, f"{name!r} is already taken")

    # ── references from action parameters ──

    def actions_in(self, workflow: Workflow) -> QuerySet[WorkflowAction]:
        """The actions configured anywhere in `workflow`."""
        return WorkflowAction.objects.filter(
            Q(status__workflow=workflow)
            | Q(transition__workflow=workflow)
            | Q(field_event__field__workflow=workflow)
        )

    def actions_naming_status(self, status: WorkflowStatus) -> list[WorkflowAction]:
        """Actions whose parameters name `status` by its key."""
        own = self.actions_in(status.workflow).filter(
            action=ActionCode.MOVE_STATUS.value, params__status=status.key
        )
        foreign = WorkflowAction.objects.filter(
            action=ActionCode.CHANGE_WORKFLOW.value,
            params__workflow=status.workflow.name,
            params__status=status.key,
        )
        return list(own) + list(foreign)

    def actions_naming_field(self, field: CustomField) -> list[WorkflowAction]:
        """Actions in the field's workflow that write it or read it in a placeholder."""
        path = f"field.{field.name}"
        return [
            a
            for a in self.actions_in(field.workflow)
            if (
                a.action in (ActionCode.SET_FIELD.value, ActionCode.CLEAR_FIELD.value)
                and a.params.get("field") == field.name
            )
            or path in placeholders(a.params)
        ]

    def actions_naming_workflow(self, workflow: Workflow) -> list[WorkflowAction]:
        """Actions in other workflows that move tickets into `workflow` by name."""
        return list(
            WorkflowAction.objects.filter(
                action=ActionCode.CHANGE_WORKFLOW.value, params__workflow=workflow.name
            ).exclude(pk__in=self.actions_in(workflow).values("pk"))
        )

    def check_unreferenced(
        self, actions: list[WorkflowAction], code: FailureCode, verb: str
    ) -> None:
        """Refuses a change that would leave `actions` naming something gone."""
        if actions:
            raise LifecycleError(
                409,
                code,
                f"it cannot be {verb}: actions name it; change those first",
                details={"action_ids": [str(a.id) for a in actions]},
            )

    def system_status(self, status_id: uuid.UUID) -> SystemStatus:
        found = SystemStatus.objects.filter(pk=status_id).first()
        if found is None:
            raise invalid([f"no system status {status_id}"])
        return found

    def audit(self, event: str, workflow: Workflow, actor: User, **payload: Any) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human",
            actor_id=actor.id,
            payload={"workflow": str(workflow.id), "name": workflow.name, **payload},
        )


# --- the configuration service ---

workflow_config = WorkflowConfig()
