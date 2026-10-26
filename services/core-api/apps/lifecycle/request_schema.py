"""Request shapes for the lifecycle endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from ninja import Field, Schema
from pydantic import StringConstraints, field_validator, model_validator

from apps.lifecycle.utils.rules import EventCode, FieldType, RuleCode
from apps.lifecycle.utils.vocabulary import ActionCode, Position, TransitionPolicy

COLOR = r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$"
Point = Literal["1", "2", "3", "4", "5", "6", "7", "8"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Canvas coordinates: finite, and small enough to fit `coordinates`.
Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1_000_000, le=1_000_000)]


def has_nul(value: Any) -> bool:
    """Whether a NUL character hides anywhere in `value`; Postgres text cannot store one."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(has_nul(k) or has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_nul(v) for v in value)
    return False


class In(Schema):
    """A lifecycle request body: no NUL characters anywhere in it."""

    @model_validator(mode="after")
    def no_nul(self) -> Any:
        if has_nul(self.model_dump(mode="json")):
            raise ValueError("text may not contain NUL characters")
        return self


def clean_options(options: list[str]) -> list[str]:
    """Select options stripped, none blank and none twice."""
    cleaned = [o.strip() for o in options]
    if any(not o for o in cleaned) or len(set(cleaned)) != len(cleaned):
        raise ValueError("options must be distinct and not blank")
    return cleaned


class SystemStatusIn(In):
    name: Name
    description: str = ""
    color: str = Field(pattern=COLOR)
    order: int | None = Field(default=None, ge=1)
    is_backlog: bool = False
    is_completed: bool = False

    @model_validator(mode="after")
    def backlog_xor_completed(self) -> SystemStatusIn:
        if self.is_backlog and self.is_completed:
            raise ValueError("a status cannot be both backlog and completed")
        return self


class SystemStatusPatch(In):
    name: Name | None = None
    description: str | None = None
    color: str | None = Field(default=None, pattern=COLOR)
    order: int | None = Field(default=None, ge=1)
    is_backlog: bool | None = None
    is_completed: bool | None = None


class ReorderIn(In):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class WorkflowIn(In):
    name: Name
    description: str = ""
    transition_policy: TransitionPolicy = TransitionPolicy.STRICT
    is_default: bool = False


class WorkflowPatch(In):
    name: Name | None = None
    description: str | None = None
    transition_policy: TransitionPolicy | None = None
    is_default: Literal[True] | None = None


class ActionIn(In):
    action: ActionCode
    params: dict[str, Any] = {}
    position: Position = Position.AFTER
    is_active: bool = True


class StatusIn(In):
    name: Name
    base_id: uuid.UUID
    color: str | None = Field(default=None, pattern=COLOR)
    coordinates: str | None = Field(default=None, pattern=r"^-?\d+\|-?\d+$")
    actions: list[ActionIn] = Field(default=[], max_length=50)


class StatusPatch(In):
    name: Name | None = None
    base_id: uuid.UUID | None = None
    color: str | None = Field(default=None, pattern=COLOR)
    coordinates: str | None = Field(default=None, pattern=r"^-?\d+\|-?\d+$")
    actions: list[ActionIn] | None = Field(default=None, max_length=50)


class PositionIn(In):
    x: Coordinate
    y: Coordinate


class RuleIn(In):
    field_id: uuid.UUID
    rule: RuleCode
    params: dict[str, Any] = {}
    is_active: bool = True


class TransitionIn(In):
    from_status_id: uuid.UUID
    to_status_id: uuid.UUID
    name: Name
    point_start: Point = "3"
    point_end: Point = "7"
    is_bidirectional: bool = False
    rules: list[RuleIn] = Field(default=[], max_length=50)
    actions: list[ActionIn] = Field(default=[], max_length=50)

    @model_validator(mode="after")
    def not_a_loop(self) -> TransitionIn:
        if self.from_status_id == self.to_status_id:
            raise ValueError("a transition must lead to a different status")
        return self


class TransitionPatch(In):
    name: Name | None = None
    point_start: Point | None = None
    point_end: Point | None = None
    is_bidirectional: bool | None = None
    rules: list[RuleIn] | None = Field(default=None, max_length=50)
    actions: list[ActionIn] | None = Field(default=None, max_length=50)


class FieldRuleIn(In):
    rule: RuleCode
    params: dict[str, Any] = {}
    is_active: bool = True


class FieldEventIn(In):
    event: EventCode
    params: dict[str, Any] = {}
    is_active: bool = True
    actions: list[ActionIn] = Field(default=[], max_length=50)


class FieldIn(In):
    name: Name
    field_type: FieldType
    options: list[str] = Field(default=[], max_length=200)
    order: int = 0

    @field_validator("options")
    @classmethod
    def distinct_options(cls, options: list[str]) -> list[str]:
        return clean_options(options)

    rules: list[FieldRuleIn] = Field(default=[], max_length=50)
    events: list[FieldEventIn] = Field(default=[], max_length=50)


class FieldPatch(In):
    name: Name | None = None
    options: list[str] | None = Field(default=None, max_length=200)
    order: int | None = None

    @field_validator("options")
    @classmethod
    def distinct_options(cls, options: list[str] | None) -> list[str] | None:
        return None if options is None else clean_options(options)

    rules: list[FieldRuleIn] | None = Field(default=None, max_length=50)
    events: list[FieldEventIn] | None = Field(default=None, max_length=50)


class MoveIn(In):
    status_id: uuid.UUID
    expected_version: int | None = None
    force: bool = False


class FieldValuesIn(In):
    values: dict[uuid.UUID, Any] = Field(max_length=100)


class ValidateFieldsIn(In):
    workflow_id: uuid.UUID
    values: dict[uuid.UUID, Any] = Field(max_length=100)


class AdoptIn(In):
    source_workflow_id: uuid.UUID
    status_mapping: dict[uuid.UUID, uuid.UUID] = {}


class ChangeWorkflowIn(In):
    status_id: uuid.UUID


class CallbackIn(In):
    success: bool
    message: str = Field(default="", max_length=2000)
    output: dict[str, Any] | None = None


class ApprovalDecisionIn(In):
    comment: str = Field(default="", max_length=2000)
