"""Sending queued email and webhook messages, retrying them, and cleaning up (F4)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import override_settings
from django.utils import timezone

from apps.lifecycle.utils.engine import lifecycle
from apps.notifications.models import Message
from apps.notifications.utils.configuration import config
from apps.notifications.utils.dispatcher import SIGNATURE_HEADER, dispatcher
from apps.notifications.utils.vocabulary import MessageState

DOWN = "apps.notifications.tests.conftest.DownRelay"
REJECTING = "apps.notifications.tests.conftest.RejectingRelay"


def email_to(user) -> Message:
    return Message.objects.get(user=user, channel="email")


def assign(ticket, user, actor):
    lifecycle.assign(ticket.id, username=user.username, team=None, actor=actor)


def make_due(message: Message) -> None:
    Message.objects.filter(pk=message.pk).update(next_attempt_at=timezone.now())


def subscribe(people, url: str = "http://localhost:5678/hook"):
    return config.subscribe(
        people["tu"],
        {
            "name": "n8n",
            "url": url,
            "events": ["ticket.assigned"],
            "secret": "a-long-enough-secret",
        },
    )


def test_an_email_is_sent_with_text_html_and_a_link(people, ticket, queue):
    """FR-F4-006."""
    assign(ticket, people["duc"], people["huy"])

    assert dispatcher.dispatch(email_to(people["duc"]).id) == MessageState.DELIVERED.value

    (sent,) = mail.outbox
    assert isinstance(sent, EmailMultiAlternatives)
    assert sent.to == ["duc.tm@example.test"]
    link = f"{settings.NOTIFICATION_PUBLIC_BASE_URL.rstrip('/')}/tickets/TKT-2026-000412"
    assert link in sent.body
    html, mime = sent.alternatives[0]
    assert mime == "text/html" and link in str(html)
    assert email_to(people["duc"]).delivered_at is not None


@override_settings(EMAIL_BACKEND=DOWN)
def test_failed_email_leaves_ticket_unchanged(people, ticket, queue):
    """AC-F4-04: after max attempts the email is failed with an error; the ticket is untouched."""
    assign(ticket, people["duc"], people["huy"])
    ticket.refresh_from_db()
    status, version = ticket.status, ticket.version
    message = email_to(people["duc"])

    for _ in range(settings.THRESHOLDS.notifications.max_attempts):
        make_due(message)
        dispatcher.dispatch(message.id)

    message.refresh_from_db()
    assert message.state == MessageState.FAILED.value
    assert message.attempts == settings.THRESHOLDS.notifications.max_attempts
    assert "relay refused the connection" in message.last_error
    ticket.refresh_from_db()
    assert (ticket.status, ticket.version, ticket.assigned_to) == (status, version, people["duc"])


@override_settings(EMAIL_BACKEND=DOWN)
def test_a_transient_failure_retries_with_backoff(people, ticket, queue):
    assign(ticket, people["duc"], people["huy"])
    message = email_to(people["duc"])

    assert dispatcher.dispatch(message.id) == MessageState.QUEUED.value

    message.refresh_from_db()
    assert message.next_attempt_at is not None
    assert message.next_attempt_at > timezone.now()
    ((sent_id, countdown),) = queue.sent
    assert sent_id == str(message.id)
    assert countdown == settings.LIFECYCLE_RETRY_BACKOFF_BASE_SEC * 2


@override_settings(EMAIL_BACKEND=REJECTING)
def test_a_refused_recipient_fails_at_once(people, ticket, queue):
    assign(ticket, people["duc"], people["huy"])
    message = email_to(people["duc"])

    assert dispatcher.dispatch(message.id) == MessageState.FAILED.value
    message.refresh_from_db()
    assert message.attempts == 1
    assert message.last_error.startswith("send_refused")
    assert queue.sent == []


def test_dispatch_twice_sends_once(people, ticket, queue):
    """Only a queued row is sent; a delivered one is never sent again."""
    assign(ticket, people["duc"], people["huy"])
    message = email_to(people["duc"])

    dispatcher.dispatch(message.id)
    assert dispatcher.dispatch(message.id) == "skipped"

    assert len(mail.outbox) == 1


def test_a_retry_not_yet_due_is_not_sent(people, ticket, queue):
    assign(ticket, people["duc"], people["huy"])
    message = email_to(people["duc"])
    Message.objects.filter(pk=message.pk).update(
        next_attempt_at=timezone.now() + timedelta(minutes=5)
    )

    assert dispatcher.dispatch(message.id) == "skipped"
    assert mail.outbox == []


def test_a_webhook_is_signed_with_the_subscriptions_secret(people, ticket, queue, host):
    """BR-F4-06: HMAC-SHA256 of the exact body in X-SmartTicket-Signature."""
    subscribe(people)
    assign(ticket, people["duc"], people["huy"])
    message = Message.objects.get(channel="webhook")

    assert dispatcher.dispatch(message.id) == MessageState.DELIVERED.value

    (call,) = host.calls
    expected = hmac.new(b"a-long-enough-secret", call["content"], hashlib.sha256).hexdigest()
    assert call["headers"][SIGNATURE_HEADER] == f"sha256={expected}"
    assert json.loads(call["content"])["event"] == "ticket.assigned"


def test_a_webhook_5xx_is_retried_and_a_4xx_is_not(people, ticket, queue, host):
    subscribe(people)
    assign(ticket, people["duc"], people["huy"])
    message = Message.objects.get(channel="webhook")

    host.status = 503
    assert dispatcher.dispatch(message.id) == MessageState.QUEUED.value
    make_due(message)
    host.status = 404
    assert dispatcher.dispatch(message.id) == MessageState.FAILED.value


def test_a_webhook_host_dropped_from_the_allow_list_is_refused(people, ticket, queue, host):
    subscribe(people)
    assign(ticket, people["duc"], people["huy"])
    message = Message.objects.get(channel="webhook")

    with override_settings(LIFECYCLE_WEBHOOK_ALLOWED_HOSTS=["example.org"]):
        assert dispatcher.dispatch(message.id) == MessageState.FAILED.value

    assert host.calls == []


def test_the_sweep_requeues_a_stuck_send_and_dispatches_due_ones(people, ticket, queue):
    assign(ticket, people["duc"], people["huy"])
    message = email_to(people["duc"])
    stuck_since = timezone.now() - timedelta(
        seconds=settings.THRESHOLDS.notifications.stuck_after_sec + 1
    )
    Message.objects.filter(pk=message.pk).update(
        state=MessageState.SENDING.value, last_attempt_at=stuck_since
    )

    result = dispatcher.sweep()

    message.refresh_from_db()
    assert message.state == MessageState.QUEUED.value
    assert (result.requeued, result.dispatched) == (1, 1)
    assert queue.ids() == [str(message.id)]


def test_the_sweep_leaves_a_recent_send_alone(people, ticket, queue):
    assign(ticket, people["duc"], people["huy"])
    message = email_to(people["duc"])
    Message.objects.filter(pk=message.pk).update(
        state=MessageState.SENDING.value, last_attempt_at=timezone.now()
    )

    assert dispatcher.sweep().requeued == 0


def test_the_purge_deletes_old_in_app_notices_only(people, ticket):
    assign(ticket, people["duc"], people["huy"])
    days = settings.THRESHOLDS.notifications.in_app_retention_days
    Message.objects.update(created_at=timezone.now() - timedelta(days=days + 1))

    assert dispatcher.purge() == 1
    assert list(Message.objects.values_list("channel", flat=True)) == ["email"]
