"""Request bodies of the SLA endpoints (F1 §h)."""

from __future__ import annotations

import datetime
import uuid

from ninja import Schema
from pydantic import Field

from apps.sla.models import Priority
from infrastructure.dtos import TicketCategory


class PolicyIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=1)
    category: TicketCategory | None = None
    priority: Priority | None = None
    response_minutes: int
    resolution_minutes: int
    calendar_id: uuid.UUID | None = None
    is_24x7: bool = False
    replaces_id: uuid.UUID | None = None


class PolicyPatch(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    order: int | None = Field(None, ge=1)
    category: TicketCategory | None = None
    priority: Priority | None = None
    response_minutes: int | None = None
    resolution_minutes: int | None = None
    calendar_id: uuid.UUID | None = None
    is_24x7: bool | None = None


class ReasonIn(Schema):
    reason: str = Field("", max_length=500)


class CalendarIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    timezone: str = Field(min_length=1, max_length=64)
    working_hours: dict[str, list[list[str]]]
    is_default: bool = False


class CalendarPatch(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    timezone: str | None = Field(None, min_length=1, max_length=64)
    working_hours: dict[str, list[list[str]]] | None = None
    is_default: bool | None = None


class HolidayIn(Schema):
    date: datetime.date | None = None
    from_date: datetime.date | None = Field(None, alias="from")
    to_date: datetime.date | None = Field(None, alias="to")
    name: str = Field(min_length=1, max_length=100)


class PreviewIn(Schema):
    category: TicketCategory | None = None
    priority: Priority
    start_at: datetime.datetime


class PriorityIn(Schema):
    priority: Priority
    reason: str = Field("", max_length=500)
    expected_version: int
