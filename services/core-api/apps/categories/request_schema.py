"""Request bodies of the category endpoints."""

from __future__ import annotations

from ninja import Schema
from pydantic import ConfigDict, Field


class CategoryPatch(Schema):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    sort_order: int | None = Field(None, ge=0, le=32767)
    reason: str = Field("", max_length=500)
