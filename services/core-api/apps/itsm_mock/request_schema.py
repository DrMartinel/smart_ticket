"""Request bodies for the runbook endpoints (F12)."""

from __future__ import annotations

from typing import Any, Literal

from ninja import Schema
from pydantic import Field, field_validator

from apps.itsm_mock.models import ExecutorKind, RunbookRisk, TargetRule


class ExecuteIn(Schema):
    payload: dict[str, Any]


class ExecutionResolveIn(Schema):
    state: Literal["succeeded", "failed"]
    note: str = Field(max_length=2000)

    @field_validator("note")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a note is required")
        return value


class CallbackIn(Schema):
    state: Literal["succeeded", "failed"]
    external_ref: str = Field(default="", max_length=500)
    error: str = Field(default="", max_length=2000)


class RunbookChangeIn(Schema):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    executor: ExecutorKind | None = None
    config: dict[str, Any] | None = None
    required_fields: list[str] | None = None
    target_rule: TargetRule | None = None
    risk: RunbookRisk | None = None
    is_active: bool | None = None

    def changes(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(mode="json").items() if v is not None}


class RunbookIn(Schema):
    code: str = Field(pattern=r"^RB-[A-Z0-9]+(-[A-Z0-9]+)*$", max_length=64)
    title: str = Field(min_length=3, max_length=200)
    executor: ExecutorKind
    config: dict[str, Any]
    required_fields: list[str]
    target_rule: TargetRule
    risk: RunbookRisk
    is_active: bool = True

    def fields(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"code"})
