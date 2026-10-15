"""Response shapes for the lifecycle endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Schema

from apps.lifecycle.models import ApprovalRequest, Transfer, TicketFieldValue
from apps.lifecycle.utils.resolver import MoveOption


class SystemStatusOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    color: str
    order: int
    is_backlog: bool
    is_completed: bool
    created_at: datetime
    updated_at: datetime


class ActionOut(Schema):
    id: uuid.UUID
    action: str
    params: dict[str, Any]
    position: str
    is_active: bool
    sort_order: int


class StatusOut(Schema):
    id: uuid.UUID
    workflow_id: uuid.UUID
    key: str
    name: str
    color: str
    order: int
    coordinates: str | None
    base: SystemStatusOut
    is_pipeline: bool
    actions: list[ActionOut]


class StatusBriefOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    color: str
    base_id: uuid.UUID
    is_pipeline: bool


class RuleOut(Schema):
    id: uuid.UUID
    field_id: uuid.UUID
    rule: str
    params: dict[str, Any]
    is_active: bool


class TransitionOut(Schema):
    id: uuid.UUID
    workflow_id: uuid.UUID
    from_status_id: uuid.UUID
    to_status_id: uuid.UUID
    name: str
    point_start: str
    point_end: str
    is_bidirectional: bool
    rules: list[RuleOut]
    actions: list[ActionOut]


class FieldRuleOut(Schema):
    id: uuid.UUID
    rule: str
    params: dict[str, Any]
    is_active: bool


class FieldEventOut(Schema):
    id: uuid.UUID
    event: str
    params: dict[str, Any]
    is_active: bool
    actions: list[ActionOut]


class FieldOut(Schema):
    id: uuid.UUID
    workflow_id: uuid.UUID
    name: str
    field_type: str
    options: list[str]
    order: int
    rules: list[FieldRuleOut]
    events: list[FieldEventOut]


class WorkflowOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    transition_policy: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class WorkflowDetailOut(WorkflowOut):
    statuses: list[StatusOut]
    transitions: list[TransitionOut]
    fields: list[FieldOut]


class ActionParamOut(Schema):
    name: str
    description: str
    type: str
    required: bool


class RuleSpecOut(Schema):
    code: str
    name: str
    description: str
    err_message: str
    params: list[str]
    field_types: list[str]


class EventSpecOut(Schema):
    code: str
    name: str
    description: str
    params: list[str]


class ActionSpecOut(Schema):
    code: str
    name: str
    description: str
    blocking: bool
    phases: list[str]
    params: list[ActionParamOut]


class CatalogOut(Schema):
    field_types: list[str]
    rules: list[RuleSpecOut]
    events: list[EventSpecOut]
    actions: list[ActionSpecOut]
    variables: dict[str, str]


class MoveOptionOut(Schema):
    status: StatusBriefOut
    transition_id: uuid.UUID | None
    transition_name: str | None
    direction: str | None
    rule_count: int

    @staticmethod
    def resolve_transition_id(obj: MoveOption) -> uuid.UUID | None:
        return obj.transition.id if obj.transition else None

    @staticmethod
    def resolve_transition_name(obj: MoveOption) -> str | None:
        return obj.transition.name if obj.transition else None

    @staticmethod
    def resolve_direction(obj: MoveOption) -> str | None:
        return obj.direction.value if obj.direction else None

    @staticmethod
    def resolve_rule_count(obj: MoveOption) -> int:
        if obj.transition is None:
            return 0
        return sum(1 for r in obj.transition.rules.all() if r.is_active)


class FieldValueOut(Schema):
    field_id: uuid.UUID
    field_name: str
    value: Any

    @staticmethod
    def resolve_field_name(obj: TicketFieldValue) -> str:
        return obj.field.name


class TicketLifecycleOut(Schema):
    public_id: str
    status: str
    workflow_status: StatusBriefOut | None
    version: int
    waiting_transform: bool
    resolved_at: datetime | None
    field_values: list[FieldValueOut]


class ActionRunOut(Schema):
    id: uuid.UUID
    action: str
    phase: str
    seq: int
    state: str
    attempt: int
    error_code: str | None
    error: str
    output: dict[str, Any] | None
    awaiting_until: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class TransferOut(Schema):
    id: uuid.UUID
    ticket_public_id: str
    trigger: str
    state: str
    direction: str | None
    failure_code: str | None
    failure_reason: str
    before_status_id: uuid.UUID | None
    after_status_id: uuid.UUID | None
    transition_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    depth: int
    created_at: datetime
    committed_at: datetime | None
    finished_at: datetime | None
    runs: list[ActionRunOut]

    @staticmethod
    def resolve_ticket_public_id(obj: Transfer) -> str:
        return obj.ticket.public_id


class ApprovalOut(Schema):
    id: uuid.UUID
    run_id: uuid.UUID
    ticket_public_id: str
    message: str
    state: str
    approver_ids: list[str]
    comment: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None

    @staticmethod
    def resolve_ticket_public_id(obj: ApprovalRequest) -> str:
        return obj.run.ticket.public_id


class AdoptOut(Schema):
    moved: int
    skipped: int


class ViolationOut(Schema):
    field_id: str
    field_name: str
    rule_id: str
    rule: str
    message: str


class ValidationOut(Schema):
    valid: bool
    violations: list[ViolationOut]
