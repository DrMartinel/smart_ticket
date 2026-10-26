"""Turning an event into messages: recipients, preferences, mandatory cells, language (F4)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.tests.conftest import assign_to
from apps.notifications.models import MatrixRule, Message, Preference, Template
from apps.notifications.utils.configuration import config
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.secrets import webhook_secrets
from apps.notifications.utils.vocabulary import (
    CATALOG,
    Channel,
    MessageState,
    NotificationEvent,
)
from apps.notifications.models import WebhookSubscription
from apps.teams.models import TeamMembership
from apps.tickets.models import PiiQuarantine
from apps.tickets.utils.crypto import build_quarantine_entries

PHONE = "0912345678"


def messages(user, event: NotificationEvent | None = None, **filters):
    rows = Message.objects.filter(user=user, **filters)
    return list(rows.filter(event=event.value) if event else rows)


def test_an_assignee_gets_an_in_app_notice_with_masked_text(people, ticket):
    """AC-F4-01: one unread in-app notice whose body keeps the placeholder."""
    assign_to(ticket, people["ha"], people["huy"])

    (notice,) = messages(people["ha"], NotificationEvent.TICKET_ASSIGNED, channel="in_app")
    assert notice.state == MessageState.DELIVERED.value
    assert notice.read_at is None
    assert "[PHONE_VN_1]" in notice.body
    assert notice.subject == "Bạn được giao TKT-2026-000412: Không vào được AWS access portal"
    assert notice.link == "/tickets/TKT-2026-000412"


def test_notice_uses_masked_text_only(people, ticket):
    """BR-F4-04: no message on any channel carries a quarantined value."""
    entries = build_quarantine_entries({"[PHONE_VN_1]": PHONE})
    PiiQuarantine.objects.store(ticket, entries)
    ticket.pii_map = {ph: str(e.ref) for ph, e in entries.items()}
    ticket.save(update_fields=["pii_map"])
    config.subscribe(
        people["tu"],
        {
            "name": "n8n",
            "url": "http://localhost:5678/hook",
            "events": ["ticket.assigned"],
            "secret": "a-long-enough-secret",
        },
    )

    assign_to(ticket, people["ha"], people["huy"])

    sent = Message.objects.filter(event=NotificationEvent.TICKET_ASSIGNED.value)
    assert {m.channel for m in sent} == {"in_app", "email", "webhook"}
    for message in sent:
        assert PHONE not in message.subject + message.body
    webhook = json.loads(sent.get(channel="webhook").body)
    assert webhook["ticket"]["subject"] == ticket.subject_masked


def test_a_preference_turns_off_email(people, ticket):
    """AC-F4-02."""
    Preference.objects.create(
        user=people["duc"], event="ticket.assigned", channel="email", enabled=False
    )

    assign_to(ticket, people["duc"], people["huy"])

    assert [m.channel for m in messages(people["duc"], NotificationEvent.TICKET_ASSIGNED)] == [
        "in_app"
    ]


def test_mandatory_cell_ignores_preference(people):
    """BR-F4-03: a stored opt-out of a mandatory cell is never applied."""
    Preference.objects.create(
        user=people["anh"], event="security.alert", channel="email", enabled=False
    )
    MatrixRule.objects.filter(event="security.alert").update(default_on=False)

    notifier.security_alert("reveal_rate_limited", actor="duc.tm", detail="20 reveals in an hour")

    assert sorted(m.channel for m in messages(people["anh"], NotificationEvent.SECURITY_ALERT)) == [
        "email",
        "in_app",
    ]


def test_rolled_back_event_sends_nothing(people, ticket, queue, django_capture_on_commit_callbacks):
    """AC-F4-05: an assignment that raises after emit leaves no message and queues no send."""
    event_id = uuid.uuid4()
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                notifier.emit(NotificationEvent.TICKET_ASSIGNED, ticket, event_id=event_id)
                raise RuntimeError("the assignment failed after emit")

    assert not Message.objects.filter(event_id=event_id).exists()
    assert queue.sent == []


def test_a_committed_event_queues_its_email_after_commit(
    people, ticket, queue, django_capture_on_commit_callbacks
):
    """BR-F4-01: sending starts only once the event's transaction commits."""
    with django_capture_on_commit_callbacks() as callbacks:
        assign_to(ticket, people["ha"], people["huy"])
        assert queue.sent == []

    for callback in callbacks:
        callback()
    (email,) = messages(people["ha"], channel="email")
    assert queue.ids() == [str(email.id)]


def test_language_follows_the_user(people, ticket):
    """AC-F4-08."""
    assign_to(ticket, people["mai"], people["huy"])

    (notice,) = messages(people["mai"], NotificationEvent.TICKET_ASSIGNED, channel="in_app")
    assert notice.subject.startswith("Assigned to you: TKT-")
    assert notice.language == "en"


def test_a_re_emitted_event_never_double_sends(people, ticket):
    """AC-F4-09: the same event id stored twice is one in-app message and one email."""
    ticket.assigned_to = people["ha"]
    ticket.save(update_fields=["assigned_to"])
    event_id = uuid.UUID("5b7e0d1a-0000-4000-8000-000000000001")

    notifier.emit(NotificationEvent.TICKET_ASSIGNED, ticket, event_id=event_id)
    notifier.emit(NotificationEvent.TICKET_ASSIGNED, ticket, event_id=event_id)

    assert sorted(m.channel for m in messages(people["ha"], event_id=event_id)) == [
        "email",
        "in_app",
    ]


def test_reassigning_tells_the_new_and_previous_assignee_and_the_team_lead(people, ticket):
    assign_to(ticket, people["duc"], people["huy"])
    Message.objects.all().delete()

    assign_to(ticket, people["ha"], people["huy"])

    event = NotificationEvent.TICKET_REASSIGNED
    assert sorted(m.channel for m in messages(people["ha"], event)) == ["email", "in_app"]
    assert [m.channel for m in messages(people["duc"], event)] == ["in_app"]
    (lead,) = messages(people["huy"], event)
    assert "duc.tm" in lead.body
    assert "workload" in lead.body


def test_a_ticket_nobody_can_take_tells_the_team_lead(people, ticket):
    assign_to(ticket, people["duc"], people["huy"])
    TeamMembership.objects.filter(team=ticket.team).update(is_available=False)
    Message.objects.all().delete()

    assign_to(ticket, None, people["huy"])

    assert messages(people["huy"], NotificationEvent.TICKET_UNASSIGNED)
    assert not messages(people["duc"])


def test_assigning_the_same_person_again_tells_nobody(people, ticket):
    assign_to(ticket, people["ha"], people["huy"])
    Message.objects.all().delete()

    assign_to(ticket, people["ha"], people["huy"])

    assert not Message.objects.exists()


def test_a_template_error_fails_the_message_and_not_the_assignment(people, ticket):
    """UC-F4-01 4x: an unknown variable fails the notice; the ticket is assigned anyway."""
    Template.objects.create(
        event="ticket.assigned",
        channel="in_app",
        language="vi",
        subject_template="{{ticket.nope}}",
        body_template="x",
    )

    assign_to(ticket, people["ha"], people["huy"])

    ticket.refresh_from_db()
    assert ticket.assigned_to == people["ha"]
    (notice,) = messages(people["ha"], channel="in_app")
    assert notice.state == MessageState.FAILED.value
    assert notice.last_error.startswith("template_error")


def test_an_emit_that_crashes_is_audited_and_the_event_goes_on(people, ticket, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("matrix unreadable")

    monkeypatch.setattr(notifier, "deliveries", broken)

    assign_to(ticket, people["ha"], people["huy"])

    ticket.refresh_from_db()
    assert ticket.assigned_to == people["ha"]
    (failed,) = AuditLog.objects.filter(event="notification_emit_failed")
    assert failed.payload["event"] == "ticket.assigned"


def test_a_user_without_an_email_address_gets_a_failed_email_to_look_at(people, ticket):
    people["ha"].email = ""
    people["ha"].save(update_fields=["email"])

    assign_to(ticket, people["ha"], people["huy"])

    (email,) = messages(people["ha"], channel="email")
    assert email.state == MessageState.FAILED.value
    assert email.last_error.startswith("no_address")


def test_an_inactive_user_is_never_notified(people, ticket):
    people["anh"].is_active = False
    people["anh"].save(update_fields=["is_active"])

    notifier.security_alert("ambiguous_role", actor="system", detail="x")

    assert not Message.objects.exists()


def test_a_matrix_cell_turned_off_drops_its_default(people, ticket):
    MatrixRule.objects.filter(event="ticket.assigned", channel="email").update(default_on=False)

    assign_to(ticket, people["ha"], people["huy"])

    assert [m.channel for m in messages(people["ha"])] == ["in_app"]


def test_a_user_can_opt_in_to_a_cell_the_matrix_turned_off(people, ticket):
    MatrixRule.objects.filter(event="ticket.assigned", channel="email").update(default_on=False)
    Preference.objects.create(
        user=people["ha"], event="ticket.assigned", channel="email", enabled=True
    )

    assign_to(ticket, people["ha"], people["huy"])

    assert sorted(m.channel for m in messages(people["ha"])) == ["email", "in_app"]


def test_a_webhook_subscription_gets_the_fixed_body(people, ticket):
    """BR-F4-06: same shape for every event, masked fields, no free template."""
    config.subscribe(
        people["tu"],
        {
            "name": "n8n",
            "url": "http://localhost:5678/hook",
            "events": ["ticket.assigned"],
            "secret": "a-long-enough-secret",
        },
    )

    assign_to(ticket, people["ha"], people["huy"])

    body = json.loads(Message.objects.get(channel=Channel.WEBHOOK.value).body)
    assert set(body) == {"event", "event_id", "occurred_at", "ticket", "data"}
    assert body["ticket"]["assignee"] == "ha.vt"
    assert body["data"]["by"] == "huy.pq"


def test_a_webhook_secret_is_stored_sealed(people):
    subscription = config.subscribe(
        people["tu"],
        {
            "name": "n8n",
            "url": "http://localhost:5678/hook",
            "events": ["sla.breached"],
            "secret": "a-long-enough-secret",
        },
    )

    stored = WebhookSubscription.objects.get(pk=subscription.pk)
    assert b"a-long-enough-secret" not in bytes(stored.secret_ciphertext)
    assert (
        webhook_secrets.open(stored.secret_ciphertext, stored.secret_nonce)
        == b"a-long-enough-secret"
    )


def test_every_catalog_event_has_a_cell_and_labels():
    for event, spec in CATALOG.items():
        assert spec.cells, event
        assert spec.label_en and spec.label_vi, event


def test_the_seeded_matrix_matches_the_catalog(db):
    seeded = set(MatrixRule.objects.values_list("event", "recipient_kind", "channel", "mandatory"))
    catalog = {
        (e.value, c.kind.value, c.channel.value, c.mandatory)
        for e, spec in CATALOG.items()
        for c in spec.cells
    }
    assert seeded == catalog


def test_a_notice_for_no_ticket_renders_without_ticket_values(people):
    notifier.emit(
        NotificationEvent.IDENTITY_BREAK_GLASS_USED,
        notice=Notice(actor="manager1", detail="admin_console, IP 10.0.0.1"),
    )

    (notice,) = messages(people["anh"], channel="in_app")
    assert notice.subject == "Đăng nhập khẩn cấp: manager1"
    assert notice.ticket is None
    assert notice.created_at > timezone.now() - timedelta(minutes=1)


def test_a_send_refused_after_commit_is_logged_not_raised(
    people, ticket, monkeypatch, django_capture_on_commit_callbacks, caplog
):
    """A broker that refuses the send after commit is logged; Django names the callback when it
    logs, so the callback must have a name (a `functools.partial` has none)."""
    from django.db import connection

    def refuse(ids):
        raise ConnectionError("broker down")

    monkeypatch.setattr(notifier, "queue_dispatch", refuse)
    with django_capture_on_commit_callbacks() as callbacks:
        assign_to(ticket, people["ha"], people["huy"])
    assert callbacks

    # Django's own robust path, outside the test's atomic block it would refuse to run in.
    monkeypatch.setattr(connection, "validate_no_atomic_block", lambda: None)
    connection.run_on_commit = [(set(), callback, True) for callback in callbacks]
    connection.run_and_clear_commit_hooks()

    assert "broker down" in caplog.text
