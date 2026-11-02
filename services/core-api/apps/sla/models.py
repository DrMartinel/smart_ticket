"""SLA calendars, holidays, policies and the clocks that run on tickets (F1, ADR-0030)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.db.models import Q, QuerySet

from apps.core.models import BaseModel
from apps.sla.utils.business_time import BusinessCalendar, parse_hours
from infrastructure.dtos import TicketCategory


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class PolicyState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class ClockKind(StrEnum):
    RESPONSE = "response"
    RESOLUTION = "resolution"


class ClockState(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    BREACHED = "breached"
    MET = "met"
    CANCELLED = "cancelled"


# Clocks still counting toward their target.
OPEN_CLOCK_STATES = (ClockState.RUNNING.value, ClockState.PAUSED.value, ClockState.BREACHED.value)


class ClockEventKind(StrEnum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    MET = "met"
    BREACH = "breach"
    RETARGET = "retarget"
    OVERRIDE = "override"
    REBUILD = "rebuild"
    CANCEL = "cancel"
    REOPEN = "reopen"


def _choices(enum: Any) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class Calendar(BaseModel):
    """Working hours per weekday in one zone; exactly one is the default."""

    name = models.CharField(max_length=100, unique=True)
    timezone = models.CharField(max_length=64)
    working_hours = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "sla_calendars"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="sla_one_default_calendar"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Holiday(BaseModel):
    """A whole day off in a calendar's zone."""

    calendar = models.ForeignKey(Calendar, on_delete=models.CASCADE, related_name="holidays")
    date = models.DateField()
    name = models.CharField(max_length=100)

    class Meta(BaseModel.Meta):
        db_table = "sla_holidays"
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["calendar", "date"], name="uniq_sla_holiday")
        ]


class PolicyQuerySet(QuerySet["Policy"]):
    def matching(self, category: str | None, priority: str | None) -> Policy | None:
        """The first active policy by order for a category and priority (BR-F1-03)."""
        return (
            self.filter(state=PolicyState.ACTIVE.value)
            .filter(Q(category__isnull=True) | Q(category=category))
            .filter(Q(priority__isnull=True) | Q(priority=priority))
            .order_by("order")
            .first()
        )


class Policy(BaseModel):
    """Response and resolution targets, in business minutes, for a category and priority."""

    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField()
    category = models.CharField(
        max_length=20, null=True, blank=True, choices=_choices(TicketCategory)
    )
    priority = models.CharField(max_length=2, null=True, blank=True, choices=_choices(Priority))
    response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()
    calendar = models.ForeignKey(
        Calendar, on_delete=models.PROTECT, null=True, blank=True, related_name="policies"
    )
    is_24x7 = models.BooleanField(default=False)
    state = models.CharField(
        max_length=10, choices=_choices(PolicyState), default=PolicyState.DRAFT.value
    )
    # The active policy this draft takes over from when approved.
    replaces = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PolicyQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "sla_policies"
        ordering = ["order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order"], condition=Q(state="active"), name="sla_active_order_unique"
            )
        ]

    def is_default(self) -> bool:
        return self.category is None and self.priority is None


class ClockQuerySet(QuerySet["Clock"]):
    def open(self) -> ClockQuerySet:
        return self.filter(state__in=OPEN_CLOCK_STATES)


class Clock(BaseModel):
    """One response or resolution clock of a ticket, with the targets it started under."""

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="sla_clocks"
    )
    kind = models.CharField(max_length=10, choices=_choices(ClockKind))
    policy = models.ForeignKey(Policy, on_delete=models.PROTECT, related_name="clocks")
    policy_snapshot = models.JSONField()
    state = models.CharField(max_length=10, choices=_choices(ClockState))
    started_at = models.DateTimeField()
    paused_at = models.DateTimeField(null=True, blank=True)
    elapsed_business_sec = models.PositiveIntegerField(default=0)
    elapsed_as_of = models.DateTimeField()
    due_at = models.DateTimeField(null=True, blank=True)
    warn_at = models.DateTimeField(null=True, blank=True)
    escalate_at = models.DateTimeField(null=True, blank=True)
    warned_at = models.DateTimeField(null=True, blank=True)
    breached_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    met_at = models.DateTimeField(null=True, blank=True)
    override_minutes = models.PositiveIntegerField(null=True, blank=True)

    objects = ClockQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "sla_clocks"
        constraints = [models.UniqueConstraint(fields=["ticket", "kind"], name="uniq_sla_clock")]
        indexes = [
            models.Index(fields=["state", "warn_at"], name="sla_clock_warn"),
            models.Index(fields=["state", "due_at"], name="sla_clock_due"),
            models.Index(fields=["state", "escalate_at"], name="sla_clock_escalate"),
        ]

    def target_minutes(self) -> int:
        """The target this clock counts to: an override, else the policy's at the start."""
        if self.override_minutes is not None:
            return self.override_minutes
        return int(self.policy_snapshot[f"{self.kind}_minutes"])

    def calendar(self, holidays: frozenset[Any]) -> BusinessCalendar:
        """The snapshot's working hours with the calendar's holidays as they are now (BR-F1-05)."""
        snap = self.policy_snapshot["calendar"]
        return BusinessCalendar(
            ZoneInfo(snap["timezone"]),
            parse_hours(snap["working_hours"]),
            holidays,
            is_24x7=bool(self.policy_snapshot["is_24x7"]),
        )

    def elapsed_at(self, at: datetime, calendar: BusinessCalendar) -> int:
        """Business seconds counted by `at`; a paused or finished clock stopped counting."""
        if self.state in (ClockState.RUNNING.value, ClockState.BREACHED.value):
            return self.elapsed_business_sec + calendar.elapsed(self.elapsed_as_of, at)
        return self.elapsed_business_sec


class ClockEvent(BaseModel):
    """What happened to a clock and how much business time it had then."""

    clock = models.ForeignKey(Clock, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=10, choices=_choices(ClockEventKind))
    at = models.DateTimeField()
    transfer = models.ForeignKey(
        "lifecycle.Transfer", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    elapsed_business_sec = models.PositiveIntegerField()

    class Meta(BaseModel.Meta):
        db_table = "sla_clock_events"
        ordering = ["at"]


class Rebuild(BaseModel):
    """A ticket whose clocks the sweep rebuilds after an `sla_update_failed` (BR-F1-11)."""

    ticket = models.OneToOneField(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="sla_rebuild"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "sla_rebuilds"
