"""Request bodies for the security inbox (F8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field


class AlertFilter(Schema):
    kind: str | None = None
    severity: Literal["critical", "high", "medium"] | None = None
    state: Literal["new", "acknowledged", "investigating", "closed", "open"] | None = None
    assignee: str | None = None
    since: datetime | None = Field(default=None, alias="from")
    until: datetime | None = Field(default=None, alias="to")


class AssignIn(Schema):
    model_config = ConfigDict(extra="forbid")

    user: str = Field(max_length=150)


class NoteIn(Schema):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(max_length=2_000)


class CloseIn(Schema):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["true_positive", "false_positive", "duplicate"]
    note: str = Field(max_length=2_000)
    duplicate_of: uuid.UUID | None = None


class ReasonIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2_000)
