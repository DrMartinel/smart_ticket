"""Security alerts and their history (F8): what security triages, raised wherever a `security_alert`
audit row is written."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from django.conf import settings
from django.db import models
from django.db.models import Case, Q, Value, When

from apps.core.models import BaseModel
from apps.security.utils.vocabulary import (
    OPEN_ALERT_STATES,
    AlertKind,
    AlertState,
    EventKind,
    Resolution,
    Severity,
)


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class SecurityAlertQuerySet(models.QuerySet["SecurityAlert"]):
    def open(self) -> SecurityAlertQuerySet:
        return self.filter(state__in=[s.value for s in OPEN_ALERT_STATES])

    def grouping(
        self, kind: AlertKind, ticket_id: object, user_id: object, since: datetime
    ) -> SecurityAlertQuerySet:
        """Open alerts a new event of `kind` joins (BR-F8-03): same ticket, else same user."""
        same = (
            Q(ticket_id=ticket_id)
            if ticket_id is not None
            else Q(ticket__isnull=True, subject_user_id=user_id)
        )
        return self.open().filter(same, kind=kind.value, last_seen_at__gte=since)

    def matching(
        self,
        *,
        kind: str | None = None,
        severity: str | None = None,
        state: str | None = None,
        assignee: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SecurityAlertQuerySet:
        """The inbox: filtered, most severe first, then oldest (UC-F8-01)."""
        qs = self.select_related("ticket__reporter", "subject_user", "assignee")
        if kind:
            qs = qs.filter(kind=kind)
        if severity:
            qs = qs.filter(severity=severity)
        if state == "open":
            qs = qs.filter(state__in=[s.value for s in OPEN_ALERT_STATES])
        elif state:
            qs = qs.filter(state=state)
        if assignee:
            qs = qs.filter(assignee__username=assignee)
        if since:
            qs = qs.filter(first_seen_at__gte=since)
        if until:
            qs = qs.filter(first_seen_at__lt=until)
        rank = Case(
            When(severity=Severity.CRITICAL.value, then=Value(0)),
            When(severity=Severity.HIGH.value, then=Value(1)),
            default=Value(2),
        )
        return qs.order_by(rank, "first_seen_at")

    def ack_overdue(self, now: datetime) -> SecurityAlertQuerySet:
        """New alerts past their ack time whose overdue notice hasn't gone out."""
        return self.filter(
            state=AlertState.NEW.value, ack_due_at__lte=now, ack_overdue_notified_at__isnull=True
        )


class SecurityAlert(BaseModel):
    kind = models.CharField(max_length=40, choices=_choices(AlertKind))
    severity = models.CharField(max_length=10, choices=_choices(Severity))
    state = models.CharField(
        max_length=15, choices=_choices(AlertState), default=AlertState.NEW.value
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_alerts",
    )
    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_alerts",
    )
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=1)
    # What the source said, never a quarantined value: a reason, a client, an IP.
    detail = models.CharField(max_length=300, blank=True, default="")
    ack_due_at = models.DateTimeField()
    ack_overdue_notified_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolution = models.CharField(
        max_length=15, choices=_choices(Resolution), null=True, blank=True
    )
    duplicate_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates"
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    requester_notified_at = models.DateTimeField(null=True, blank=True)

    objects = SecurityAlertQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "security_alerts"
        indexes = [
            models.Index(fields=["state", "ack_due_at"], name="security_alert_due"),
            models.Index(fields=["kind", "last_seen_at"], name="security_alert_group"),
        ]

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_ALERT_STATES


class SecurityAlertEvent(BaseModel):
    alert = models.ForeignKey(SecurityAlert, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=15, choices=_choices(EventKind))
    audit_log_id = models.UUIDField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note_masked = models.TextField(blank=True, default="")
    at = models.DateTimeField()

    class Meta(BaseModel.Meta):
        db_table = "security_alert_events"
        ordering = ["at"]
