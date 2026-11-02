"""The security inbox (F8): alerts for `security` only; managers get counts (BR-F8-01)."""

from __future__ import annotations

import uuid

from django.utils import timezone
from ninja import Query, Router, Status

from apps.accounts.models import RefreshSession, UserRole
from apps.accounts.permissions import AuthedRequest, SessionAuth, require_role
from apps.audit.models import AuditLog
from apps.security.models import SecurityAlert
from apps.security.request_schema import AlertFilter, AssignIn, CloseIn, NoteIn, ReasonIn
from apps.security.response_schema import (
    ActivityOut,
    AlertDetailOut,
    AlertEventOut,
    AlertRowOut,
    SessionOut,
    SummaryCellOut,
    SummaryOut,
)
from apps.security.utils.alerts import security_alerts
from apps.security.utils.vocabulary import Resolution, SecurityError, SecurityRefusal
from apps.tickets.models import Ticket
from apps.tickets.response_schema import TicketOut

router = Router(tags=["security"])

_SUMMARY_DAYS = 30


def _alert(alert_id: uuid.UUID) -> SecurityAlert:
    alert = (
        SecurityAlert.objects.select_related("ticket__reporter", "subject_user", "assignee")
        .filter(pk=alert_id)
        .first()
    )
    if alert is None:
        raise SecurityError(404, SecurityRefusal.NOT_FOUND, "no such alert")
    return alert


def _detail(alert_id: uuid.UUID) -> AlertDetailOut:
    alert = _alert(alert_id)
    user = alert.subject_user
    sessions = (
        [
            SessionOut(
                client=s.client,
                ip_address=s.ip_address,
                user_agent=s.user_agent,
                created_at=s.created_at,
                expires_at=s.expires_at,
            )
            for s in RefreshSession.objects.filter(
                user=user, revoked_at__isnull=True, expires_at__gt=timezone.now()
            ).order_by("-created_at")
        ]
        if user
        else []
    )
    activity = (
        [
            ActivityOut(event=a.event, occurred_at=a.occurred_at, ticket_id=a.ticket_id)
            for a in AuditLog.objects.filter(actor_id=user.id).order_by("-occurred_at")[:20]
        ]
        if user
        else []
    )
    return AlertDetailOut.build(alert, sessions, activity)


@router.get("/alerts", auth=SessionAuth(), response=list[AlertRowOut])
@require_role(UserRole.SECURITY)
def list_alerts(request: AuthedRequest, filters: Query[AlertFilter]) -> list[AlertRowOut]:
    rows = SecurityAlert.objects.matching(**filters.model_dump())
    return [AlertRowOut.of(a) for a in rows[:500]]


@router.get("/alerts/{alert_id}", auth=SessionAuth(), response=AlertDetailOut)
@require_role(UserRole.SECURITY)
def get_alert(request: AuthedRequest, alert_id: uuid.UUID) -> AlertDetailOut:
    return _detail(alert_id)


@router.post("/alerts/{alert_id}/ack", auth=SessionAuth(), response=AlertDetailOut)
@require_role(UserRole.SECURITY)
def acknowledge(request: AuthedRequest, alert_id: uuid.UUID) -> AlertDetailOut:
    security_alerts.acknowledge(alert_id, request.auth)
    return _detail(alert_id)


@router.post("/alerts/{alert_id}/assign", auth=SessionAuth(), response=AlertDetailOut)
@require_role(UserRole.SECURITY)
def assign(request: AuthedRequest, alert_id: uuid.UUID, payload: AssignIn) -> AlertDetailOut:
    security_alerts.assign(alert_id, request.auth, payload.user)
    return _detail(alert_id)


@router.post("/alerts/{alert_id}/notes", auth=SessionAuth(), response=AlertEventOut)
@require_role(UserRole.SECURITY)
def add_note(request: AuthedRequest, alert_id: uuid.UUID, payload: NoteIn) -> AlertEventOut:
    return AlertEventOut.of(security_alerts.note(alert_id, request.auth, payload.note))


@router.post("/alerts/{alert_id}/close", auth=SessionAuth(), response=AlertDetailOut)
@require_role(UserRole.SECURITY)
def close(request: AuthedRequest, alert_id: uuid.UUID, payload: CloseIn) -> AlertDetailOut:
    security_alerts.close(
        alert_id, request.auth, Resolution(payload.resolution), payload.note, payload.duplicate_of
    )
    return _detail(alert_id)


@router.post("/alerts/{alert_id}/reopen", auth=SessionAuth(), response=AlertDetailOut)
@require_role(UserRole.SECURITY)
def reopen(request: AuthedRequest, alert_id: uuid.UUID, payload: NoteIn) -> AlertDetailOut:
    security_alerts.reopen(alert_id, request.auth, payload.note)
    return _detail(alert_id)


@router.post("/alerts/{alert_id}/release-ticket", auth=SessionAuth(), response=TicketOut)
@require_role(UserRole.SECURITY)
def release_ticket(request: AuthedRequest, alert_id: uuid.UUID, payload: ReasonIn) -> Ticket:
    return security_alerts.release(alert_id, request.auth, payload.reason)


@router.post("/alerts/{alert_id}/notify-requester", auth=SessionAuth(), response={204: None})
@require_role(UserRole.SECURITY)
def notify_requester(request: AuthedRequest, alert_id: uuid.UUID) -> Status[None]:
    security_alerts.notify_requester(alert_id, request.auth)
    return Status(204, None)


@router.post("/alerts/{alert_id}/end-sessions", auth=SessionAuth(), response=AlertDetailOut)
@require_role(UserRole.SECURITY)
def end_sessions(request: AuthedRequest, alert_id: uuid.UUID) -> AlertDetailOut:
    security_alerts.end_sessions(alert_id, request.auth)
    return _detail(alert_id)


@router.get("/summary", auth=SessionAuth(), response=SummaryOut)
@require_role(UserRole.SECURITY, UserRole.MANAGER)
def summary(request: AuthedRequest) -> SummaryOut:
    cells = security_alerts.summary(_SUMMARY_DAYS)
    return SummaryOut(days=_SUMMARY_DAYS, cells=[SummaryCellOut(**c) for c in cells])
