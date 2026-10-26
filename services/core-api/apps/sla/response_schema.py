"""Response shapes of the SLA endpoints (F1 §h)."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from ninja import Schema

from apps.sla.models import Calendar, Clock, Policy

if TYPE_CHECKING:
    from apps.sla.utils.clocks import Badge


class PolicyOut(Schema):
    id: uuid.UUID
    name: str
    order: int
    category: str | None
    priority: str | None
    response_minutes: int
    resolution_minutes: int
    calendar: str | None
    is_24x7: bool
    state: str
    replaces: uuid.UUID | None
    created_by: str | None
    approved_by: str | None
    approved_at: datetime.datetime | None

    @staticmethod
    def resolve_calendar(policy: Policy) -> str | None:
        return policy.calendar.name if policy.calendar else None

    @staticmethod
    def resolve_replaces(policy: Policy) -> uuid.UUID | None:
        return policy.replaces_id

    @staticmethod
    def resolve_created_by(policy: Policy) -> str | None:
        return policy.created_by.username if policy.created_by else None

    @staticmethod
    def resolve_approved_by(policy: Policy) -> str | None:
        return policy.approved_by.username if policy.approved_by else None


class HolidayOut(Schema):
    id: uuid.UUID
    date: datetime.date
    name: str


class CalendarOut(Schema):
    id: uuid.UUID
    name: str
    timezone: str
    working_hours: dict[str, list[list[str]]]
    is_default: bool
    holidays_count: int

    @staticmethod
    def resolve_holidays_count(calendar: Calendar) -> int:
        return calendar.holidays.count()


class DueOut(Schema):
    due_at: datetime.datetime
    warn_at: datetime.datetime


class PreviewOut(Schema):
    policy: str
    calendar: str
    response: DueOut
    resolution: DueOut


class ClockOut(Schema):
    kind: str
    state: str
    target_minutes: int
    elapsed_minutes: int
    remaining_minutes: int
    due_at: datetime.datetime | None
    warn_at: datetime.datetime | None
    met_at: datetime.datetime | None
    breached_at: datetime.datetime | None
    paused: bool
    breached: bool
    warned: bool


class TicketSlaOut(Schema):
    priority: str | None
    policy: str | None
    calendar: str | None
    clocks: list[ClockOut]


class BadgeClockOut(Schema):
    kind: str
    state: str
    due_at: datetime.datetime | None
    met_at: datetime.datetime | None
    elapsed_minutes: int
    target_minutes: int


class SlaBadgeOut(Schema):
    kind: str
    level: str
    remaining_minutes: int
    due_at: datetime.datetime | None
    policy: str
    calendar: str
    clocks: list[BadgeClockOut]


class BreachOut(Schema):
    ticket: str
    subject: str
    team: str | None
    assignee: str | None
    priority: str | None
    kind: str
    state: str
    due_at: datetime.datetime | None
    breached_at: datetime.datetime | None
    warned_at: datetime.datetime | None
    sla: SlaBadgeOut | None

    @staticmethod
    def resolve_sla(clock: Clock) -> Badge | None:
        from apps.sla.utils.clocks import sla_clocks

        return sla_clocks.badge(clock.ticket)

    @staticmethod
    def resolve_ticket(clock: Clock) -> str:
        return clock.ticket.public_id

    @staticmethod
    def resolve_subject(clock: Clock) -> str:
        return clock.ticket.subject_masked

    @staticmethod
    def resolve_team(clock: Clock) -> str | None:
        return clock.ticket.assigned_team

    @staticmethod
    def resolve_assignee(clock: Clock) -> str | None:
        return clock.ticket.assigned_to.username if clock.ticket.assigned_to else None

    @staticmethod
    def resolve_priority(clock: Clock) -> str | None:
        return clock.ticket.priority
