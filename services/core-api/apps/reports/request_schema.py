"""Query filters of the F10 report endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from ninja import Field, Schema

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class SlaFilter(Schema):
    month: str | None = Field(default=None, pattern=MONTH)
    team: str | None = None
    priority: str | None = None
    category: str | None = None


class SlaTicketsFilter(SlaFilter):
    kind: Literal["response", "resolution"] = "resolution"
    state: Literal["met", "breached", "excluded"] | None = None
    page: int = Field(default=1, ge=1)


class TeamFilter(Schema):
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")


class DaysFilter(Schema):
    days: int | None = Field(default=None, ge=1, le=366)


class ReviewerFilter(DaysFilter):
    reviewer: str | None = None


class WeeksFilter(Schema):
    weeks: int | None = Field(default=None, ge=1, le=52)


class MonthFilter(Schema):
    month: str | None = Field(default=None, pattern=MONTH)


class CsatFilter(MonthFilter):
    team: str | None = None
