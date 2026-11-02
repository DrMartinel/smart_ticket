"""Alerts for the last 30 days of `security_alert` audit rows, grouped as the service groups them
(F8 §g). Their overdue notices are marked sent: history doesn't page anyone."""

from __future__ import annotations

from datetime import timedelta

from django.db import migrations
from django.utils import timezone

# The audit reason each writer used before F8 -> the alert kind.
KINDS = {
    "pii_critical": "pii_critical",
    "injection_detected": "injection_detected",
    "refresh_token_reused": "refresh_token_reused",
    "break_glass_used": "break_glass_sign_in",
    "break_glass_account_in_keycloak": "break_glass_in_keycloak",
    "ambiguous_role": "ambiguous_role",
    "reveal_rate_limited": "reveal_rate_limited",
    "decrypt_failed": "decrypt_failed",
    "access_log_failed": "reveal_failed",
    "credential_in_comment": "credential_in_reply",
    "credential_in_rating": "credential_in_reply",
}
SEVERITY = {
    "pii_critical": "critical",
    "credential_in_reply": "critical",
    "refresh_token_reused": "critical",
    "break_glass_sign_in": "critical",
    "break_glass_in_keycloak": "critical",
}
WINDOW = timedelta(minutes=60)
ACK_MINUTES = {"critical": 60, "high": 240, "medium": 570}


def backfill(apps, schema_editor):
    AuditLog = apps.get_model("audit", "AuditLog")
    Alert = apps.get_model("security", "SecurityAlert")
    Event = apps.get_model("security", "SecurityAlertEvent")
    Ticket = apps.get_model("tickets", "Ticket")
    User = apps.get_model("accounts", "User")
    now = timezone.now()
    open_: dict[tuple, object] = {}
    rows = AuditLog.objects.filter(
        event="security_alert", occurred_at__gte=now - timedelta(days=30)
    ).order_by("occurred_at")
    for row in rows:
        reason = row.payload.get("reason_code") or row.payload.get("reason")
        kind = KINDS.get(reason)
        if kind is None:
            continue
        ticket = Ticket.objects.filter(pk=row.ticket_id).first() if row.ticket_id else None
        user = User.objects.filter(pk=row.actor_id).first() if row.actor_id else None
        if ticket is not None and user is None:
            user = ticket.reporter
        key = (kind, ticket.pk if ticket else None, None if ticket else (user.pk if user else None))
        alert = open_.get(key)
        if alert is not None and row.occurred_at - alert.last_seen_at <= WINDOW:
            alert.count += 1
            alert.last_seen_at = row.occurred_at
            alert.save(update_fields=["count", "last_seen_at"])
            Event.objects.create(
                alert=alert, kind="regrouped", audit_log_id=row.id, at=row.occurred_at
            )
            continue
        severity = SEVERITY.get(kind, "high")
        alert = Alert.objects.create(
            kind=kind,
            severity=severity,
            state="new",
            ticket=ticket,
            subject_user=user,
            first_seen_at=row.occurred_at,
            last_seen_at=row.occurred_at,
            detail=f"backfilled from the audit log ({reason})",
            ack_due_at=row.occurred_at + timedelta(minutes=ACK_MINUTES[severity]),
            ack_overdue_notified_at=now,
        )
        Event.objects.create(alert=alert, kind="raised", audit_log_id=row.id, at=row.occurred_at)
        open_[key] = alert


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0001_initial"),
        ("audit", "0001_initial"),
        ("tickets", "0008_conversations_comments_ratings"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
