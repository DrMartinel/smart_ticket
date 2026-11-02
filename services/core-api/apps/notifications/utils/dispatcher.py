"""Sends queued email and webhook messages, retries them, and cleans up (ADR-0033, BR-F4-05)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import smtplib
import uuid
from dataclasses import dataclass
from datetime import timedelta
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.notifications.models import Message
from apps.notifications.utils.secrets import webhook_secrets
from apps.notifications.utils.vocabulary import Channel, FailureReason, MessageState
from infrastructure.outbound import OutboundRefused, OutboundUnavailable, outbound

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-SmartTicket-Signature"


class TransientSendError(Exception):
    """The relay or host may accept the message later."""


class PermanentSendError(Exception):
    """Sending this message again won't help."""


@dataclass(frozen=True)
class SweepResult:
    requeued: int
    dispatched: int


class Dispatcher:
    """Sends one message at most once per claim; a failure changes the message, nothing else."""

    def dispatch(self, message_id: uuid.UUID) -> str:
        """Sends a due queued message; returns the state it ends in, or 'skipped'."""
        message = self.claim(message_id)
        if message is None:
            return "skipped"
        try:
            if message.channel == Channel.EMAIL.value:
                self.send_email(message)
            else:
                self.send_webhook(message)
        except TransientSendError as e:
            return self.retry_later(message, str(e))
        except PermanentSendError as e:
            return self.fail(message, f"{FailureReason.SEND_REFUSED}: {e}")
        except Exception as e:  # noqa: BLE001 — a crashing send fails its message, never the worker
            logger.exception("notifications: sending message %s crashed", message.id)
            return self.fail(message, f"{FailureReason.SEND_FAILED}: {type(e).__name__}: {e}")
        Message.objects.filter(pk=message.pk, state=MessageState.SENDING.value).update(
            state=MessageState.DELIVERED.value, delivered_at=timezone.now(), last_error=""
        )
        return MessageState.DELIVERED.value

    def claim(self, message_id: uuid.UUID) -> Message | None:
        """Marks a due queued message `sending` and counts the attempt; None if it isn't one."""
        with transaction.atomic():
            message = (
                Message.objects.select_for_update(skip_locked=True, of=("self",))
                .due(timezone.now())
                .exclude(channel=Channel.IN_APP.value)
                .select_related("user", "subscription")
                .filter(pk=message_id)
                .first()
            )
            if message is None:
                return None
            message.state = MessageState.SENDING.value
            message.attempts += 1
            message.last_attempt_at = timezone.now()
            message.save(update_fields=["state", "attempts", "last_attempt_at"])
        return message

    def retry_later(self, message: Message, error: str) -> str:
        """Re-queues after a transient failure with backoff, or fails at the last attempt."""
        if message.attempts >= settings.THRESHOLDS.notifications.max_attempts:
            return self.fail(message, f"{FailureReason.SEND_FAILED}: {error}")
        delay = min(
            settings.LIFECYCLE_RETRY_BACKOFF_BASE_SEC * 2**message.attempts,
            settings.LIFECYCLE_RETRY_BACKOFF_MAX_SEC,
        )
        written = Message.objects.filter(pk=message.pk, state=MessageState.SENDING.value).update(
            state=MessageState.QUEUED.value,
            next_attempt_at=timezone.now() + timedelta(seconds=delay),
            last_error=f"{FailureReason.SEND_FAILED}: {error}"[:2000],
        )
        if written:
            from apps.notifications import tasks

            tasks.dispatch.apply_async((str(message.id),), countdown=delay)
        return MessageState.QUEUED.value

    def fail(self, message: Message, error: str) -> str:
        Message.objects.filter(pk=message.pk, state=MessageState.SENDING.value).update(
            state=MessageState.FAILED.value, last_error=error[:2000], next_attempt_at=None
        )
        return MessageState.FAILED.value

    # ── the channels ──

    def send_email(self, message: Message) -> None:
        """Sends the text and HTML parts with a link to the page the notice opens (FR-F4-006)."""
        assert message.user is not None
        url = (
            settings.NOTIFICATION_PUBLIC_BASE_URL.rstrip("/") + message.link if message.link else ""
        )
        text = f"{message.body}\n\n{url}" if url else message.body
        html = "".join(f"<p>{escape(line)}</p>" for line in message.body.splitlines() if line)
        if url:
            html += f'<p><a href="{escape(url)}">{escape(url)}</a></p>'
        email = EmailMultiAlternatives(message.subject, text, None, [message.user.email])
        email.attach_alternative(html, "text/html")
        try:
            email.send(fail_silently=False)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
            raise PermanentSendError(str(e)) from e
        except smtplib.SMTPResponseException as e:
            if e.smtp_code >= 500:
                raise PermanentSendError(f"{e.smtp_code} {e.smtp_error!r}") from e
            raise TransientSendError(f"{e.smtp_code} {e.smtp_error!r}") from e
        except (OSError, smtplib.SMTPException) as e:
            raise TransientSendError(str(e)) from e

    def send_webhook(self, message: Message) -> None:
        """POSTs the stored JSON signed with the subscription's secret, to an allowed host only."""
        subscription = message.subscription
        assert subscription is not None
        if not subscription.is_active:
            raise PermanentSendError("the subscription is inactive")
        content = message.body.encode("utf-8")
        key = webhook_secrets.open(subscription.secret_ciphertext, subscription.secret_nonce)
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: "sha256=" + hmac.new(key, content, hashlib.sha256).hexdigest(),
            "X-SmartTicket-Event": message.event,
            "X-SmartTicket-Delivery": str(message.id),
        }
        try:
            response = outbound.send(
                subscription.url, method="POST", content=content, headers=headers
            )
        except OutboundRefused as e:
            raise PermanentSendError(str(e)) from e
        except OutboundUnavailable as e:
            raise TransientSendError(str(e)) from e
        if response.ok:
            return
        error = f"{subscription.url} answered {response.status}: {response.text[:200]}"
        if response.status >= 500 or response.status == 429:
            raise TransientSendError(error)
        raise PermanentSendError(error)

    # ── people and beat ──

    def retry(self, rows: QuerySet[Message], actor: User, *, all_failed: bool) -> int:
        """Puts failed messages back in the queue for a fresh set of attempts, audited."""
        with transaction.atomic():
            ids = list(
                rows.filter(state=MessageState.FAILED.value)
                .exclude(channel=Channel.IN_APP.value)
                .select_for_update()
                .values_list("id", flat=True)
            )
            Message.objects.filter(pk__in=ids).update(
                state=MessageState.QUEUED.value, attempts=0, next_attempt_at=None
            )
            AuditLog.objects.record(
                "notif_delivery_retried",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "count": len(ids),
                    "all_failed": all_failed,
                    "ids": [str(i) for i in ids[:100]],
                },
            )
            if ids:
                from apps.notifications.utils.notifier import notifier

                transaction.on_commit(lambda: notifier.queue_dispatch(ids), robust=True)
        return len(ids)

    def sweep(self) -> SweepResult:
        """Re-queues messages stuck `sending`, then dispatches every due queued one."""
        now = timezone.now()
        stuck_before = now - timedelta(seconds=settings.THRESHOLDS.notifications.stuck_after_sec)
        requeued = Message.objects.filter(
            state=MessageState.SENDING.value, last_attempt_at__lt=stuck_before
        ).update(state=MessageState.QUEUED.value, next_attempt_at=None)
        from apps.notifications import tasks

        due = list(
            Message.objects.due(now)
            .exclude(channel=Channel.IN_APP.value)
            .values_list("id", flat=True)
        )
        for message_id in due:
            tasks.dispatch.delay(str(message_id))
        return SweepResult(requeued=requeued, dispatched=len(due))

    def purge(self) -> int:
        """Deletes in-app messages past `notifications.in_app_retention_days`."""
        days = settings.THRESHOLDS.notifications.in_app_retention_days
        deleted, _ = Message.objects.filter(
            channel=Channel.IN_APP.value, created_at__lt=timezone.now() - timedelta(days=days)
        ).delete()
        return deleted


# --- the dispatcher ---

dispatcher = Dispatcher()
