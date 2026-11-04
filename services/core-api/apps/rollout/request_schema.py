"""Request bodies for rollout control (F9)."""

from __future__ import annotations

from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class FlagOnIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2_000)
    gate_override_reason: str = Field(default="", max_length=2_000)
    # Gate values that aren't computed: {metric: {value, evidence}} (owner, 2026-10-26).
    entered_values: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ReasonIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2_000)


class GateChangeIn(Schema):
    model_config = ConfigDict(extra="forbid")

    threshold: float
    window_days: int | None = Field(default=None, ge=1, le=365)
    reason: str = Field(max_length=2_000)
