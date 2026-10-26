"""What security sees of an alert, and what a manager sees of all of them (F8)."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.utils import timezone
from ninja import Schema

from apps.security.models import SecurityAlert, SecurityAlertEvent
from apps.security.utils.vocabulary import CREDENTIAL_KINDS, AlertKind


class AlertTicketOut(Schema):
    public_id: str
    subject_masked: str
    body_masked: str
    status: str
    pii_level: str
    reporter: str


class AlertRowOut(Schema):
    id: uuid.UUID
    kind: str
    severity: str
    state: str
    ticket: AlertTicketOut | None
    subject_user: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    count: int
    detail: str
    ack_due_at: datetime
    overdue: bool
    acknowledged_at: datetime | None
    assignee: str | None
    resolution: str | None

    @classmethod
    def of(cls, alert: SecurityAlert) -> AlertRowOut:
        ticket = alert.ticket
        return cls(
            id=alert.id,
            kind=alert.kind,
            severity=alert.severity,
            state=alert.state,
            ticket=AlertTicketOut(
                public_id=ticket.public_id,
                subject_masked=ticket.subject_masked,
                body_masked=ticket.body_masked,
                status=ticket.status,
                pii_level=ticket.pii_level,
                reporter=ticket.reporter.username,
            )
            if ticket
            else None,
            subject_user=alert.subject_user.username if alert.subject_user else None,
            first_seen_at=alert.first_seen_at,
            last_seen_at=alert.last_seen_at,
            count=alert.count,
            detail=alert.detail,
            ack_due_at=alert.ack_due_at,
            overdue=alert.acknowledged_at is None and alert.ack_due_at <= timezone.now(),
            acknowledged_at=alert.acknowledged_at,
            assignee=alert.assignee.username if alert.assignee else None,
            resolution=alert.resolution,
        )


class AlertEventOut(Schema):
    kind: str
    actor: str | None
    note_masked: str
    at: datetime

    @classmethod
    def of(cls, event: SecurityAlertEvent) -> AlertEventOut:
        return cls(
            kind=event.kind,
            actor=event.actor.username if event.actor else None,
            note_masked=event.note_masked,
            at=event.at,
        )


class SessionOut(Schema):
    client: str
    ip_address: str | None
    user_agent: str
    created_at: datetime
    expires_at: datetime


class ActivityOut(Schema):
    event: str
    occurred_at: datetime
    ticket_id: uuid.UUID | None


class AlertDetailOut(AlertRowOut):
    events: list[AlertEventOut]
    sessions: list[SessionOut]
    recent_activity: list[ActivityOut]
    duplicate_of: uuid.UUID | None
    requester_notified_at: datetime | None
    can_release: bool
    can_notify_requester: bool

    @classmethod
    def build(
        cls, alert: SecurityAlert, sessions: list[SessionOut], activity: list[ActivityOut]
    ) -> AlertDetailOut:
        row = AlertRowOut.of(alert)
        return cls(
            **row.model_dump(),
            events=[AlertEventOut.of(e) for e in alert.events.select_related("actor")],
            sessions=sessions,
            recent_activity=activity,
            duplicate_of=alert.duplicate_of_id,
            requester_notified_at=alert.requester_notified_at,
            can_release=alert.ticket is not None and alert.ticket.status == "blocked",
            can_notify_requester=alert.ticket is not None
            and AlertKind(alert.kind) in CREDENTIAL_KINDS,
        )


class SummaryCellOut(Schema):
    kind: str
    state: str
    count: int


class SummaryOut(Schema):
    days: int
    cells: list[SummaryCellOut]
