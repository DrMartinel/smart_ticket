"""Reveals quarantined PII to a person, one value at a time, and exports the access log (F5)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.notifications.utils.notifier import notifier
from apps.review.models import ReviewItem
from apps.tickets.models import PiiAccessLog, PiiQuarantine, Ticket
from apps.tickets.request_schema import RevealReason
from apps.tickets.utils import crypto
from apps.tickets.utils.masking import mask_regex_tier
from apps.tickets.utils.patterns import PIILevel, placeholder_level
from config.settings.base import PiiRevealThresholds

REASON_MIN, REASON_MAX = 10, 500


class RevealRefusal(StrEnum):
    REVEAL_NOT_ALLOWED = "reveal_not_allowed"
    CRITICAL_NEEDS_SECURITY = "critical_needs_security"
    PLACEHOLDER_NOT_FOUND = "placeholder_not_found"
    QUARANTINE_EXPIRED = "quarantine_expired"
    REASON_REQUIRED = "reason_required"
    REASON_HAS_SECRET = "reason_has_secret"
    REVEAL_RATE_LIMITED = "reveal_rate_limited"
    ACCESS_LOG_FAILED = "access_log_failed"
    DECRYPT_FAILED = "decrypt_failed"


class RevealError(CodedError):
    """A refused reveal."""

    code: RevealRefusal

    def __init__(self, status: int, code: RevealRefusal, message: str) -> None:
        super().__init__(status, code, message, {})


@dataclass(frozen=True)
class Revealed:
    placeholder: str
    value: str
    shown_until: datetime


ACCESS_LOG_COLUMNS = (
    "accessed_at",
    "actor",
    "ticket",
    "placeholder",
    "reason_code",
    "reason",
    "review_item",
    "outcome",
)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def spreadsheet_safe(value: str) -> str:
    """The value, prefixed with ' when a spreadsheet would read it as a formula."""
    return f"'{value}" if value.startswith(_FORMULA_START) else value


class PiiReveal:
    """The one way core-api reads raw PII back out of `pii_quarantine`."""

    def __init__(self, thresholds: PiiRevealThresholds) -> None:
        self.thresholds = thresholds

    def reveal(
        self,
        *,
        public_id: str,
        actor: User,
        placeholder: str,
        reason_code: RevealReason,
        reason: str,
        trace_id: str | None = None,
    ) -> Revealed:
        """Logs, decrypts and audits one placeholder's value in one transaction."""
        ticket = Ticket.objects.filter(public_id=public_id).first()
        now = timezone.now()
        try:
            if ticket is None or placeholder not in ticket.pii_map:
                raise RevealError(404, RevealRefusal.PLACEHOLDER_NOT_FOUND, "no such placeholder")
            review_item = self.check_access(ticket, actor, placeholder)
            masked_reason = self.check_reason(reason)
            with transaction.atomic():
                self.check_rate(actor)
                value, log = self.read_logged(
                    ticket, actor, placeholder, reason_code, masked_reason, review_item, now
                )
                AuditLog.objects.record(
                    "pii_revealed",
                    actor_type="human",
                    actor_id=actor.id,
                    ticket_id=ticket.id,
                    payload={
                        "placeholder": placeholder,
                        "reason_code": reason_code.value,
                        "access_log": str(log.id),
                    },
                    trace_id=trace_id,
                )
        except RevealError as refused:
            self.record_refusal(ticket, actor, placeholder, refused.code, refused.status, trace_id)
            raise
        return Revealed(
            placeholder=placeholder,
            value=value,
            shown_until=now + timedelta(seconds=self.thresholds.display_seconds),
        )

    def check_access(self, ticket: Ticket, actor: User, placeholder: str) -> ReviewItem | None:
        """Security, the holder of a claimed review item, or the assignee (BR-F5-01, 02)."""
        if placeholder_level(placeholder) is PIILevel.CRITICAL and not actor.is_security:
            raise RevealError(
                403, RevealRefusal.CRITICAL_NEEDS_SECURITY, "only security may reveal a credential"
            )
        if actor.is_security:
            return None
        claimed = ReviewItem.objects.filter(ticket=ticket, state="claimed", claimed_by=actor)
        review_item = claimed.order_by("-claimed_at").first()
        if review_item is None and ticket.assigned_to_id != actor.id:
            raise RevealError(
                403,
                RevealRefusal.REVEAL_NOT_ALLOWED,
                "reveal needs a claimed review item or the ticket's assignment",
            )
        return review_item

    def check_reason(self, reason: str) -> str:
        """The reason, masked by the regex tier; refused if empty, too long or holding a secret."""
        reason = reason.strip()
        if not REASON_MIN <= len(reason) <= REASON_MAX:
            raise RevealError(
                422,
                RevealRefusal.REASON_REQUIRED,
                f"a reason of {REASON_MIN}-{REASON_MAX} characters is required",
            )
        masked, level = mask_regex_tier(reason)
        if level is PIILevel.CRITICAL:
            raise RevealError(
                422, RevealRefusal.REASON_HAS_SECRET, "the reason contains a password or a key"
            )
        return masked

    def check_rate(self, actor: User) -> None:
        """Refuses once the actor's reveals and refused attempts in the last hour reach the
        limit (BR-F5-07); holds a per-actor lock until the reveal's transaction ends."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"pii_reveal:{actor.id}"])
        hour_ago = timezone.now() - timedelta(hours=1)
        attempts = (
            PiiAccessLog.objects.by_actor_since(actor, hour_ago).count()
            + AuditLog.objects.filter(
                event="pii_reveal_refused", actor_id=actor.id, occurred_at__gte=hour_ago
            )
            .exclude(payload__reason=RevealRefusal.REVEAL_RATE_LIMITED.value)
            .count()
        )
        if attempts >= self.thresholds.max_per_user_per_hour:
            raise RevealError(
                429,
                RevealRefusal.REVEAL_RATE_LIMITED,
                "hourly reveal limit reached; security alerted",
            )

    def read_logged(
        self,
        ticket: Ticket,
        actor: User,
        placeholder: str,
        reason_code: RevealReason,
        reason: str,
        review_item: ReviewItem | None,
        now: datetime,
    ) -> tuple[str, PiiAccessLog]:
        """Locks the quarantine row, writes the access-log row, then decrypts."""
        entry = (
            PiiQuarantine.objects.select_for_update()
            .filter(ref=ticket.pii_map[placeholder], ticket=ticket, expires_at__gt=now)
            .first()
        )
        if entry is None:
            raise RevealError(410, RevealRefusal.QUARANTINE_EXPIRED, "the value has expired")
        try:
            log = PiiAccessLog.objects.create(
                ref=entry.ref,
                actor=actor,
                ticket=ticket,
                placeholder=placeholder,
                reason_code=reason_code.value,
                reason=reason,
                review_item=review_item,
            )
        except DatabaseError as e:
            raise RevealError(
                500, RevealRefusal.ACCESS_LOG_FAILED, "the access log could not be written"
            ) from e
        try:
            return crypto.decrypt(bytes(entry.ciphertext), bytes(entry.nonce)), log
        except Exception as e:
            raise RevealError(
                500, RevealRefusal.DECRYPT_FAILED, "the value could not be decrypted"
            ) from e

    def record_refusal(
        self,
        ticket: Ticket | None,
        actor: User,
        placeholder: str,
        code: RevealRefusal,
        status: int,
        trace_id: str | None,
    ) -> None:
        """Audits a refused or failed reveal outside its rolled-back transaction, alerting
        security on a failure and on the first rate-limit refusal in an hour."""
        events = (
            ["pii_reveal_failed", "security_alert"] if status >= 500 else ["pii_reveal_refused"]
        )
        if (
            code is RevealRefusal.REVEAL_RATE_LIMITED
            and not AuditLog.objects.filter(
                event="security_alert",
                actor_id=actor.id,
                payload__reason=code.value,
                occurred_at__gte=timezone.now() - timedelta(hours=1),
            ).exists()
        ):
            events.append("security_alert")
        for event in events:
            AuditLog.objects.record(
                event,
                actor_type="human",
                actor_id=actor.id,
                ticket_id=ticket.id if ticket else None,
                payload={"reason": code.value, "placeholder": placeholder[:40]},
                trace_id=trace_id,
            )
        if "security_alert" in events:
            notifier.security_alert(
                code.value,
                actor=actor.username,
                detail=f"PII reveal of {placeholder[:40]} by {actor.username}",
                ticket=ticket,
            )

    def export_log(self, rows: Any, actor: User, filters: dict[str, Any]) -> str:
        """The rows as CSV, with no values, audited as `pii_access_log_exported`."""
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(ACCESS_LOG_COLUMNS)
        count = 0
        for row in rows:
            writer.writerow(
                [
                    spreadsheet_safe(str(cell))
                    for cell in (
                        row.accessed_at.isoformat(),
                        row.actor.username,
                        row.ticket.public_id,
                        row.placeholder,
                        row.reason_code,
                        row.reason,
                        row.review_item_id or "",
                        row.outcome,
                    )
                ]
            )
            count += 1
        AuditLog.objects.record(
            "pii_access_log_exported",
            actor_type="human",
            actor_id=actor.id,
            payload={"filters": filters, "rows": count},
        )
        return out.getvalue()
