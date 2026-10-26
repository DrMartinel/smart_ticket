"""
Workflow configuration (system statuses, workflows, statuses, transitions,
custom fields, rules, events, actions) and the lifecycle's runtime records
(transfers, action runs, approvals). ADR-0028.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models
from django.db.models import F, Q, QuerySet

from apps.core.models import BaseModel
from apps.lifecycle.utils.rules import EventCode, FieldType, RuleCode
from apps.lifecycle.utils.vocabulary import (
    OPEN_TRANSFER_STATES,
    ActionCode,
    TRIAGE_STATUSES,
    ApprovalState,
    Direction,
    FailureCode,
    Phase,
    PipelineStatus,
    Position,
    RunState,
    TransferState,
    TransitionPolicy,
    Trigger,
)

if TYPE_CHECKING:
    from apps.tickets.models import Ticket


def _choices(enum: Any) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


_PIPELINE_KEYS = frozenset(s.value for s in PipelineStatus)
_TRIAGE_KEYS = frozenset(s.value for s in TRIAGE_STATUSES)
_POINTS = [(str(i), str(i)) for i in range(1, 9)]


class SystemStatus(BaseModel):
    """A global lifecycle stage every workflow status maps onto."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    color = models.CharField(max_length=9)
    order = models.IntegerField(default=0)
    is_backlog = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_system_statuses"
        ordering = ["order", "name"]
        constraints = [
            models.CheckConstraint(
                condition=~(Q(is_backlog=True) & Q(is_completed=True)),
                name="chk_system_status_backlog_xor_completed",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class WorkflowManager(models.Manager["Workflow"]):
    def default(self) -> Workflow:
        """The workflow new tickets start in, seeded again if it has gone missing."""
        found = self.filter(is_default=True).first()
        if found is not None:
            return found
        from apps.lifecycle.seed import seed_default_workflow

        return seed_default_workflow(SystemStatus, Workflow, WorkflowStatus)

    def of_ticket(self, ticket: Ticket) -> Workflow:
        """The workflow `ticket` is in; the default one for a ticket that predates workflows."""
        if ticket.workflow_status_id is None:
            return self.default()
        return self.get(statuses__id=ticket.workflow_status_id)


class Workflow(BaseModel):
    """A named set of statuses and transitions a ticket moves through."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    transition_policy = models.CharField(
        max_length=10, choices=_choices(TransitionPolicy), default=TransitionPolicy.STRICT.value
    )
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkflowManager()

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_workflows"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="uq_one_default_workflow"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class WorkflowStatusManager(models.Manager["WorkflowStatus"]):
    def of_ticket(self, ticket: Ticket) -> WorkflowStatus | None:
        """The status `ticket` is in; for a ticket that predates workflows, the default
        workflow's status with its `status` key, if there is one."""
        statuses = self.select_related("base", "workflow")
        if ticket.workflow_status_id is not None:
            return statuses.get(pk=ticket.workflow_status_id)
        return statuses.filter(workflow__is_default=True, key=ticket.status).first()


class WorkflowStatus(BaseModel):
    """One stage of a workflow; `key` is what `Ticket.status` holds while a ticket is in it."""

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="statuses")
    base = models.ForeignKey(
        SystemStatus, on_delete=models.PROTECT, related_name="workflow_statuses"
    )
    key = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=9)
    order = models.IntegerField(default=0)
    coordinates = models.CharField(max_length=50, null=True, blank=True)
    # Entering it pauses the ticket's SLA clocks; leaving resumes them (F1, BR-F1-07).
    pauses_sla = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkflowStatusManager()

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_workflow_statuses"
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["workflow", "key"], name="uq_workflow_status_key"),
            models.UniqueConstraint(fields=["workflow", "name"], name="uq_workflow_status_name"),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_id}:{self.key}"

    @property
    def is_pipeline(self) -> bool:
        """Whether this is one of the statuses only the pipeline enters."""
        return self.key in _PIPELINE_KEYS

    @property
    def is_triage(self) -> bool:
        """Whether a ticket here belongs to the pipeline or its requester."""
        return self.key in _TRIAGE_KEYS


class Transition(BaseModel):
    """A move a person may make from one status to another, with its gates and automation."""

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="transitions")
    from_status = models.ForeignKey(
        WorkflowStatus, on_delete=models.CASCADE, related_name="outgoing"
    )
    to_status = models.ForeignKey(WorkflowStatus, on_delete=models.CASCADE, related_name="incoming")
    name = models.CharField(max_length=100)
    point_start = models.CharField(max_length=1, choices=_POINTS, default="3")
    point_end = models.CharField(max_length=1, choices=_POINTS, default="7")
    is_bidirectional = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_transitions"
        constraints = [
            models.CheckConstraint(
                condition=~Q(from_status=F("to_status")), name="chk_transition_not_self"
            ),
            models.UniqueConstraint(fields=["from_status", "to_status"], name="uq_transition_pair"),
        ]

    def direction_from(self, status_id: Any) -> Direction | None:
        """The direction a ticket at `status_id` takes this transition in, if it can."""
        if self.from_status_id == status_id:
            return Direction.FORWARD
        if self.is_bidirectional and self.to_status_id == status_id:
            return Direction.REVERSE
        return None

    def destination_from(self, status_id: Any) -> Any:
        """The status a ticket at `status_id` reaches by this transition."""
        return self.to_status_id if self.from_status_id == status_id else self.from_status_id


class CustomField(BaseModel):
    """A per-workflow field on tickets, which rules gate and events watch."""

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=100)
    field_type = models.CharField(max_length=20, choices=_choices(FieldType))
    options = models.JSONField(default=list, blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_custom_fields"
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["workflow", "name"], name="uq_custom_field_name"),
        ]


class TransitionRule(BaseModel):
    """A gate on a transition: the ticket's value of `field` must pass `rule`."""

    transition = models.ForeignKey(Transition, on_delete=models.CASCADE, related_name="rules")
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="+")
    rule = models.CharField(max_length=30, choices=_choices(RuleCode))
    params = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_transition_rules"


class FieldRule(BaseModel):
    """A check every write of `field` must pass."""

    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="rules")
    rule = models.CharField(max_length=30, choices=_choices(RuleCode))
    params = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_field_rules"


class FieldEvent(BaseModel):
    """Runs its actions when a write of `field` fires `event`."""

    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=30, choices=_choices(EventCode))
    params = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_field_events"


class WorkflowAction(BaseModel):
    """An action configured on exactly one of a status, a transition or a field event."""

    status = models.ForeignKey(
        WorkflowStatus, null=True, blank=True, on_delete=models.CASCADE, related_name="actions"
    )
    transition = models.ForeignKey(
        Transition, null=True, blank=True, on_delete=models.CASCADE, related_name="actions"
    )
    field_event = models.ForeignKey(
        FieldEvent, null=True, blank=True, on_delete=models.CASCADE, related_name="actions"
    )
    action = models.CharField(max_length=30, choices=_choices(ActionCode))
    params = models.JSONField(default=dict, blank=True)
    position = models.CharField(
        max_length=6, choices=_choices(Position), default=Position.AFTER.value
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_workflow_actions"
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status__isnull=False, transition__isnull=True, field_event__isnull=True)
                    | Q(status__isnull=True, transition__isnull=False, field_event__isnull=True)
                    | Q(status__isnull=True, transition__isnull=True, field_event__isnull=False)
                ),
                name="chk_workflow_action_one_owner",
            ),
        ]


class TicketFieldValue(BaseModel):
    """A ticket's value of one custom field."""

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="field_values"
    )
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="values")
    value = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_ticket_field_values"
        constraints = [
            models.UniqueConstraint(fields=["ticket", "field"], name="uq_ticket_field_value"),
        ]


class TransferQuerySet(QuerySet["Transfer"]):
    def open(self) -> TransferQuerySet:
        """Transfers whose move or actions are still in flight."""
        return self.filter(state__in=[s.value for s in OPEN_TRANSFER_STATES])

    def failed_queue(self) -> TransferQuerySet:
        """Failed transfers, newest first, for a person to retry or dismiss."""
        return (
            self.filter(state=TransferState.FAILED.value)
            .select_related("ticket", "before_status", "after_status", "actor")
            .order_by("-created_at")
        )


class Transfer(BaseModel):
    """One status change of one ticket: the unit of locking, auditing and retry."""

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="transfers")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trigger = models.CharField(max_length=10, choices=_choices(Trigger))
    before_status = models.ForeignKey(
        WorkflowStatus, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    after_status = models.ForeignKey(
        WorkflowStatus, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    transition = models.ForeignKey(
        Transition, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    direction = models.CharField(max_length=7, choices=_choices(Direction), null=True, blank=True)
    state = models.CharField(
        max_length=10, choices=_choices(TransferState), default=TransferState.PENDING.value
    )
    failure_code = models.CharField(
        max_length=40, choices=_choices(FailureCode), null=True, blank=True
    )
    failure_reason = models.TextField(blank=True, default="")
    depth = models.PositiveSmallIntegerField(default=0)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = TransferQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_transfers"
        indexes = [models.Index(fields=["ticket", "-created_at"], name="idx_transfer_ticket")]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket"],
                condition=Q(state__in=[s.value for s in OPEN_TRANSFER_STATES]),
                name="uq_one_open_transfer_per_ticket",
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_TRANSFER_STATES


class ActionRun(BaseModel):
    """One execution of one configured action, with its parameters as they were when planned."""

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="action_runs"
    )
    transfer = models.ForeignKey(
        Transfer, null=True, blank=True, on_delete=models.CASCADE, related_name="runs"
    )
    field_event = models.ForeignKey(
        FieldEvent, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_action = models.ForeignKey(
        WorkflowAction, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=30, choices=_choices(ActionCode))
    params = models.JSONField(default=dict)
    phase = models.CharField(max_length=6, choices=_choices(Phase))
    seq = models.PositiveIntegerField()
    depth = models.PositiveSmallIntegerField(default=0)
    state = models.CharField(
        max_length=10, choices=_choices(RunState), default=RunState.QUEUED.value
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    resolved_params = models.JSONField(null=True, blank=True)
    output = models.JSONField(null=True, blank=True)
    error_code = models.CharField(
        max_length=40, choices=_choices(FailureCode), null=True, blank=True
    )
    error = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=120, unique=True)
    awaiting_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_action_runs"
        ordering = ["seq"]
        indexes = [
            models.Index(fields=["transfer", "seq"], name="idx_action_run_transfer"),
            models.Index(fields=["state", "started_at"], name="idx_action_run_state"),
        ]


class ApprovalRequestQuerySet(QuerySet["ApprovalRequest"]):
    def pending_for(self, user: Any) -> ApprovalRequestQuerySet:
        """The approvals `user` can still answer, oldest first."""
        return (
            self.filter(state=ApprovalState.PENDING.value, approver_ids__contains=[str(user.id)])
            .select_related("run__ticket")
            .order_by("created_at")
        )


class ApprovalRequest(BaseModel):
    """A `require_approval` run waiting for one of its approvers."""

    run = models.OneToOneField(ActionRun, on_delete=models.CASCADE, related_name="approval")
    approver_ids = models.JSONField(default=list)
    message = models.TextField(blank=True, default="")
    state = models.CharField(
        max_length=10, choices=_choices(ApprovalState), default=ApprovalState.PENDING.value
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)

    objects = ApprovalRequestQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "lifecycle_approval_requests"

    def can_be_decided_by(self, user_id: Any) -> bool:
        return str(user_id) in self.approver_ids
