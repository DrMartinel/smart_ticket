"""Security alerts: raised wherever a `security_alert` audit row is written, grouped, timed, and
triaged by security (F8)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import RefusedCall, User, UserRole
from apps.audit.models import AuditLog
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.review.models import SECURITY_QUEUES
from apps.security.models import SecurityAlert, SecurityAlertEvent
from apps.security.utils.vocabulary import (
    CREDENTIAL_KINDS,
    SEVERITY,
    AlertKind,
    AlertState,
    EventKind,
    Resolution,
    SecurityError,
    SecurityRefusal,
)
from apps.sla.utils.business_time import BusinessCalendar, parse_hours

if TYPE_CHECKING:
    from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


class SecurityAlerts:
    """Raises alerts and carries out security's triage on them."""

    # ── raising (BR-F8-02, BR-F8-03) ──

    def raise_(
        self,
        kind: AlertKind,
        *,
        actor_type: str = "system",
        actor_id: uuid.UUID | None = None,
        ticket: Ticket | None = None,
        subject_user: User | None = None,
        payload: dict[str, Any] | None = None,
        reason: str | None = None,
        detail: str = "",
        notify: bool = True,
        trace_id: str | None = None,
    ) -> SecurityAlert:
        """Writes the `security_alert` audit row and raises a new alert or adds to an open one of
        the same kind and ticket (else user) in the grouping window, in the caller's transaction.
        `reason` is the source's own code for the audit row; it defaults to the kind."""
        with transaction.atomic():
            audit = AuditLog.objects.record(
                "security_alert",
                actor_type=actor_type,
                actor_id=actor_id,
                ticket_id=ticket.id if ticket else None,
                payload={
                    "reason": reason or kind.value,
                    "alert_kind": kind.value,
                    **(payload or {}),
                },
                trace_id=trace_id,
            )
            now = timezone.now()
            subject = str(ticket.id) if ticket else str(subject_user.id if subject_user else "-")
            self.lock(f"security:{kind.value}:{subject}")
            window = timedelta(minutes=settings.THRESHOLDS.security.group_window_minutes)
            existing = (
                SecurityAlert.objects.select_for_update()
                .grouping(
                    kind,
                    ticket.id if ticket else None,
                    subject_user.id if subject_user else None,
                    now - window,
                )
                .order_by("-last_seen_at")
                .first()
            )
            if existing is not None:
                existing.count += 1
                existing.last_seen_at = now
                existing.save(update_fields=["count", "last_seen_at"])
                self.event(existing, EventKind.REGROUPED, now, audit_log_id=audit.id)
                return existing
            severity = SEVERITY[kind]
            alert = SecurityAlert.objects.create(
                kind=kind.value,
                severity=severity.value,
                ticket=ticket,
                subject_user=subject_user,
                first_seen_at=now,
                last_seen_at=now,
                detail=detail[:300],
                ack_due_at=self.ack_due(severity.value, now),
            )
            self.event(alert, EventKind.RAISED, now, audit_log_id=audit.id)
            if notify:
                notifier.security_alert(
                    reason or kind.value, actor="system", detail=detail or kind.value, ticket=ticket
                )
            return alert

    def lock(self, key: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [key])

    def ack_due(self, severity: str, at: datetime) -> datetime:
        """The ack target in business time on the default calendar (BR-F8-04)."""
        from apps.sla.models import Calendar
        from apps.sla.utils.clocks import holidays_of

        minutes = settings.THRESHOLDS.security.ack_business_minutes[severity]
        calendar = Calendar.objects.filter(is_default=True).first()
        if calendar is None:
            return at + timedelta(minutes=minutes)
        business = BusinessCalendar(
            ZoneInfo(calendar.timezone),
            parse_hours(calendar.working_hours),
            holidays_of(calendar.id),
        )
        return business.add(at, minutes * 60)

    def event(
        self,
        alert: SecurityAlert,
        kind: EventKind,
        at: datetime,
        *,
        actor: User | None = None,
        note: str = "",
        audit_log_id: uuid.UUID | None = None,
    ) -> SecurityAlertEvent:
        return SecurityAlertEvent.objects.create(
            alert=alert,
            kind=kind.value,
            actor=actor,
            note_masked=note,
            at=at,
            audit_log_id=audit_log_id,
        )

    # ── triage (UC-F8-01) ──

    def locked(self, alert_id: uuid.UUID) -> SecurityAlert:
        alert = SecurityAlert.objects.select_for_update().filter(pk=alert_id).first()
        if alert is None:
            raise SecurityError(404, SecurityRefusal.NOT_FOUND, "no such alert")
        return alert

    def acknowledge(self, alert_id: uuid.UUID, actor: User) -> SecurityAlert:
        with transaction.atomic():
            alert = self.locked(alert_id)
            if alert.state != AlertState.NEW.value:
                raise SecurityError(409, SecurityRefusal.NOT_NEW, "already acknowledged")
            now = timezone.now()
            alert.state = AlertState.ACKNOWLEDGED.value
            alert.acknowledged_by, alert.acknowledged_at = actor, now
            alert.save(update_fields=["state", "acknowledged_by", "acknowledged_at"])
            self.event(alert, EventKind.ACK, now, actor=actor)
            self.audit("security_alert_acknowledged", alert, actor)
        return alert

    def assign(self, alert_id: uuid.UUID, actor: User, username: str) -> SecurityAlert:
        """Gives the alert to a security person; an acknowledged one starts investigating."""
        target = User.objects.filter(
            username=username, role=UserRole.SECURITY.value, is_active=True
        ).first()
        if target is None:
            raise SecurityError(422, SecurityRefusal.NOT_SECURITY, f"{username} isn't security")
        with transaction.atomic():
            alert = self.locked(alert_id)
            if not alert.is_open:
                raise SecurityError(409, SecurityRefusal.ALREADY_CLOSED, "the alert is closed")
            now = timezone.now()
            if alert.state == AlertState.NEW.value:
                alert.acknowledged_by, alert.acknowledged_at = actor, now
                self.event(alert, EventKind.ACK, now, actor=actor)
            alert.assignee = target
            alert.state = AlertState.INVESTIGATING.value
            alert.save(update_fields=["assignee", "state", "acknowledged_by", "acknowledged_at"])
            self.event(alert, EventKind.STATE, now, actor=actor, note=f"assigned to {username}")
            self.audit("security_alert_assigned", alert, actor, assignee=username)
        return alert

    def note(self, alert_id: uuid.UUID, actor: User, text: str) -> SecurityAlertEvent:
        """A masked note on the alert's history."""
        from apps.tickets.utils.masking import mask_regex_tier

        masked, _ = mask_regex_tier(text.strip())
        if not masked:
            raise SecurityError(422, SecurityRefusal.NOTE_REQUIRED, "write a note")
        with transaction.atomic():
            alert = self.locked(alert_id)
            return self.event(alert, EventKind.NOTE, timezone.now(), actor=actor, note=masked)

    def close(
        self,
        alert_id: uuid.UUID,
        actor: User,
        resolution: Resolution,
        note: str,
        duplicate_of: uuid.UUID | None = None,
    ) -> SecurityAlert:
        """Closes with a resolution and a note; a true positive on a blocked ticket decides its
        review item `approve`, keeping it blocked."""
        from apps.tickets.utils.masking import mask_regex_tier

        masked, _ = mask_regex_tier(note.strip())
        if not masked:
            raise SecurityError(422, SecurityRefusal.NOTE_REQUIRED, "a closing note is required")
        if resolution is Resolution.DUPLICATE and duplicate_of is None:
            raise SecurityError(
                422, SecurityRefusal.DUPLICATE_REQUIRED, "name the alert this duplicates"
            )
        with transaction.atomic():
            alert = self.locked(alert_id)
            if not alert.is_open:
                raise SecurityError(409, SecurityRefusal.ALREADY_CLOSED, "already closed")
            now = timezone.now()
            if alert.acknowledged_at is None:
                alert.acknowledged_by, alert.acknowledged_at = actor, now
            alert.state = AlertState.CLOSED.value
            alert.resolution = resolution.value
            alert.duplicate_of_id = duplicate_of if resolution is Resolution.DUPLICATE else None
            alert.closed_by, alert.closed_at = actor, now
            alert.save()
            self.event(alert, EventKind.STATE, now, actor=actor, note=masked)
            if resolution is Resolution.TRUE_POSITIVE and alert.ticket is not None:
                self.confirm_block(alert.ticket, actor, masked)
            self.audit("security_alert_closed", alert, actor, resolution=resolution.value)
        return alert

    def confirm_block(self, ticket: Ticket, actor: User, note: str) -> None:
        """Agrees with the router's block: the open security review item is decided `approve`."""
        from apps.review.models import ReviewItem
        from apps.review.request_schema import DecisionIn
        from apps.review.utils import review_decisions

        item = ReviewItem.objects.filter(
            ticket=ticket, queue__in=SECURITY_QUEUES, state__in=ReviewItem.OPEN_STATES
        ).first()
        if item is not None and ticket.status == "blocked":
            review_decisions.decide(
                item,
                actor,
                DecisionIn(action_taken="approve", override_reason=note, time_spent_sec=0),
            )

    def reopen(self, alert_id: uuid.UUID, actor: User, note: str) -> SecurityAlert:
        from apps.tickets.utils.masking import mask_regex_tier

        masked, _ = mask_regex_tier(note.strip())
        if not masked:
            raise SecurityError(422, SecurityRefusal.NOTE_REQUIRED, "say why it's reopened")
        with transaction.atomic():
            alert = self.locked(alert_id)
            if alert.state != AlertState.CLOSED.value:
                raise SecurityError(409, SecurityRefusal.NOT_CLOSED, "the alert is open")
            now = timezone.now()
            alert.state = AlertState.INVESTIGATING.value
            alert.resolution = None
            alert.duplicate_of = None
            alert.closed_by = alert.closed_at = None
            alert.assignee = alert.assignee or actor
            alert.save()
            self.event(alert, EventKind.STATE, now, actor=actor, note=masked)
            self.audit("security_alert_reopened", alert, actor)
        return alert

    # ── the ticket behind an alert (UC-F8-02, UC-F8-03) ──

    def release(self, alert_id: uuid.UUID, actor: User, reason: str) -> Ticket:
        """Sends a blocked ticket to a person, never back through the AI (BR-F8-06): its security
        review item is decided `reject` with the reason and a `low_confidence` item opens."""
        from apps.lifecycle.utils.engine import lifecycle
        from apps.lifecycle.utils.vocabulary import PipelineStatus
        from apps.review.models import ReviewItem
        from apps.review.request_schema import DecisionIn
        from apps.review.utils import review_decisions
        from apps.tickets.models import Ticket
        from apps.tickets.utils.masking import mask_regex_tier
        from apps.tickets.utils.router import ReviewQueue

        masked, _ = mask_regex_tier(reason.strip())
        if not masked:
            raise SecurityError(422, SecurityRefusal.REASON_REQUIRED, "say why it's released")
        with transaction.atomic():
            alert = self.locked(alert_id)
            if alert.ticket_id is None:
                raise SecurityError(409, SecurityRefusal.NO_TICKET, "the alert has no ticket")
            ticket = Ticket.objects.select_for_update().get(pk=alert.ticket_id)
            if ticket.status != PipelineStatus.BLOCKED.value:
                raise SecurityError(409, SecurityRefusal.NOT_BLOCKED, "the ticket isn't blocked")
            item = ReviewItem.objects.filter(
                ticket=ticket, queue__in=SECURITY_QUEUES, state__in=ReviewItem.OPEN_STATES
            ).first()
            if item is not None:
                review_decisions.decide(
                    item,
                    actor,
                    DecisionIn(action_taken="reject", override_reason=masked, time_spent_sec=0),
                )
            lifecycle.system_move(ticket, PipelineStatus.PENDING_REVIEW)
            ReviewItem.objects.create(
                ticket=ticket,
                ai_run=item.ai_run if item else None,
                queue=ReviewQueue.LOW_CONFIDENCE.value,
                priority=2,
            )
            now = timezone.now()
            self.event(alert, EventKind.RELEASE, now, actor=actor, note=masked)
            if alert.state == AlertState.NEW.value:
                alert.state = AlertState.ACKNOWLEDGED.value
                alert.acknowledged_by, alert.acknowledged_at = actor, now
                alert.save(update_fields=["state", "acknowledged_by", "acknowledged_at"])
            AuditLog.objects.record(
                "security_ticket_released",
                actor_type="human",
                actor_id=actor.id,
                ticket_id=ticket.id,
                payload={"alert": str(alert.id), "ticket_public_id": ticket.public_id},
            )
        return ticket

    def notify_requester(self, alert_id: uuid.UUID, actor: User) -> SecurityAlert:
        """Tells the requester a credential they sent is exposed and must be changed (BR-F8-05)."""
        with transaction.atomic():
            alert = self.locked(alert_id)
            if alert.ticket is None:
                raise SecurityError(409, SecurityRefusal.NO_TICKET, "the alert has no ticket")
            if alert.kind not in CREDENTIAL_KINDS:
                raise SecurityError(
                    409, SecurityRefusal.NOT_A_CREDENTIAL, "the alert isn't about a credential"
                )
            now = timezone.now()
            notifier.emit(
                NotificationEvent.SECURITY_CREDENTIAL_EXPOSED,
                alert.ticket,
                Notice(actor=actor.username, data={"alert": str(alert.id)}),
                event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"credential_exposed:{alert.id}"),
            )
            alert.requester_notified_at = now
            alert.save(update_fields=["requester_notified_at"])
            self.event(alert, EventKind.NOTIFIED, now, actor=actor)
            self.audit("security_requester_notified", alert, actor)
        return alert

    def end_sessions(self, alert_id: uuid.UUID, actor: User) -> int:
        """Ends every sign-in of the alert's user (UC-F8-04 step 2)."""
        from apps.accounts.utils import sessions

        with transaction.atomic():
            alert = self.locked(alert_id)
            if alert.subject_user is None:
                raise SecurityError(409, SecurityRefusal.NO_USER, "the alert names no user")
            ended = sessions.revoke_user(alert.subject_user, "security_alert")
            self.event(
                alert, EventKind.STATE, timezone.now(), actor=actor, note=f"{ended} sign-ins ended"
            )
            self.audit("security_sessions_ended", alert, actor, ended=ended)
        return ended

    def summary(self, days: int) -> list[dict[str, Any]]:
        """Alert counts by kind and state over `days`, with no ticket or user (BR-F8-01)."""
        since = timezone.now() - timedelta(days=days)
        return [
            dict(row)
            for row in SecurityAlert.objects.filter(first_seen_at__gte=since)
            .values("kind", "state")
            .annotate(count=Count("id"))
            .order_by("kind", "state")
        ]

    def audit(self, event: str, alert: SecurityAlert, actor: User, **extra: Any) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human",
            actor_id=actor.id,
            ticket_id=alert.ticket_id,
            payload={"alert": str(alert.id), "kind": alert.kind, **extra},
        )

    # ── the sweep ──

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Overdue-ack notices once per alert, refusal bursts, and old refused calls purged."""
        now = now or timezone.now()
        overdue = 0
        for alert in SecurityAlert.objects.ack_overdue(now).select_related("ticket"):
            with transaction.atomic():
                updated = SecurityAlert.objects.filter(
                    pk=alert.pk, ack_overdue_notified_at__isnull=True
                ).update(ack_overdue_notified_at=now)
                if updated:
                    notifier.emit(
                        NotificationEvent.SECURITY_ACK_OVERDUE,
                        alert.ticket,
                        Notice(
                            reason=alert.kind,
                            detail=f"{alert.severity}, due {alert.ack_due_at:%Y-%m-%d %H:%M} UTC",
                            data={"alert": str(alert.id), "kind": alert.kind},
                        ),
                        event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"ack_overdue:{alert.id}"),
                    )
                    overdue += 1
        bursts = self.detect_bursts(now)
        RefusedCall.objects.filter(at__lt=now - timedelta(days=1)).delete()
        return {"ack_overdue": overdue, "bursts": bursts}

    def detect_bursts(self, now: datetime) -> int:
        """One `access_denied_burst` alert per user over the refusal count in the window (BR-F8-08)."""
        th = settings.THRESHOLDS.security
        rows = (
            RefusedCall.objects.since(now - timedelta(minutes=th.access_denied_window_minutes))
            .values("user")
            .annotate(n=Count("id"))
            .filter(n__gte=th.access_denied_burst)
        )
        raised = 0
        for row in rows:
            user = User.objects.get(pk=row["user"])
            window = timedelta(minutes=th.group_window_minutes)
            if SecurityAlert.objects.grouping(
                AlertKind.ACCESS_DENIED_BURST, None, user.id, now - window
            ).exists():
                continue
            self.raise_(
                AlertKind.ACCESS_DENIED_BURST,
                actor_id=user.id,
                subject_user=user,
                payload={"refusals": row["n"], "window_minutes": th.access_denied_window_minutes},
                detail=f"{user.username}: {row['n']} refused calls",
            )
            raised += 1
        return raised


# --- the security alerts service ---

security_alerts = SecurityAlerts()
