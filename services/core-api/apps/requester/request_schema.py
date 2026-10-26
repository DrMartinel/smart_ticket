"""Request bodies for the requester's ticket endpoints (F3)."""

from __future__ import annotations

from ninja import Schema
from pydantic import ConfigDict, Field


class ReplyIn(Schema):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    body: str = Field(min_length=1, max_length=10_000)


class ReopenIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2_000)


class RatingIn(Schema):
    model_config = ConfigDict(extra="forbid")

    score: int
    comment: str | None = Field(default=None, max_length=2_000)
