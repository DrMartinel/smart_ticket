"""Request bodies for rollout and threshold control (F9)."""

from __future__ import annotations

from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class FlagRequestIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2_000)
    gate_override_reason: str = Field(default="", max_length=2_000)
    # Gate values that aren't computed: {metric: {value, evidence}} (owner, 2026-10-26).
    entered_values: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ApproveIn(Schema):
    model_config = ConfigDict(extra="forbid")

    gate_override_reason: str = Field(default="", max_length=2_000)


class ReasonIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2_000)


class GateChangeIn(Schema):
    model_config = ConfigDict(extra="forbid")

    threshold: float
    window_days: int | None = Field(default=None, ge=1, le=365)
    reason: str = Field(max_length=2_000)


class ChangeRequestIn(Schema):
    model_config = ConfigDict(extra="forbid")

    yaml_text: str = Field(max_length=200_000)
    evidence: str = Field(default="", max_length=5_000)


class CommentIn(Schema):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(default="", max_length=2_000)
