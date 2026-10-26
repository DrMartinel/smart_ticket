"""The notification endpoints: inbox, preferences, matrix, deliveries, webhooks, templates (F4 §h)."""

from __future__ import annotations

import json

from django.conf import settings
from django.test import Client, override_settings

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.notifications.tests.conftest import assign_to
from apps.notifications.models import MatrixRule, Message, Template, WebhookSubscription
from apps.notifications.utils.vocabulary import MessageState

JSON = "application/json"


def put(client: Client, url: str, body):
    return client.put(url, json.dumps(body), content_type=JSON)


def post(client: Client, url: str, body=None):
    return client.post(url, json.dumps(body or {}), content_type=JSON)


def matrix_cell(event: str, kind: str, channel: str) -> MatrixRule:
    return MatrixRule.objects.get(event=event, recipient_kind=kind, channel=channel)


# ── inbox ──


def test_the_inbox_lists_my_unread_notices_with_the_poll_interval(api_as, people, ticket):
    """UC-F4-02 / spec §g stage 4."""
    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])

    body = api_as(people["duc"]).get("/api/notifications?unread=true").json()

    assert body["unread"] == 1
    assert body["poll_sec"] == settings.NOTIFICATION_POLL_SEC
    (item,) = body["items"]
    assert item["event"] == "ticket.assigned"
    assert item["link"] == "/tickets/TKT-2026-000412"
    assert item["ticket"] == "TKT-2026-000412"
    assert item["read_at"] is None


def test_the_inbox_never_shows_someone_elses_notices(api_as, people, ticket):
    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])

    body = api_as(people["ha"]).get("/api/notifications").json()

    assert body == {"unread": 0, "poll_sec": settings.NOTIFICATION_POLL_SEC, "items": []}


def test_reading_a_notice_marks_it_and_only_mine(api_as, people, ticket):
    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])
    notice = Message.objects.get(user=people["duc"], channel="in_app")

    assert api_as(people["ha"]).post(f"/api/notifications/{notice.id}/read").status_code == 404
    assert api_as(people["duc"]).post(f"/api/notifications/{notice.id}/read").status_code == 204

    notice.refresh_from_db()
    assert notice.read_at is not None


def test_an_email_message_is_not_an_inbox_notice(api_as, people, ticket):
    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])
    email = Message.objects.get(user=people["duc"], channel="email")

    response = api_as(people["duc"]).post(f"/api/notifications/{email.id}/read")

    assert response.status_code == 404
    assert response.json()["code"] == "notification_not_found"


def test_read_all_clears_the_count(api_as, people, ticket):
    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])
    client = api_as(people["duc"])

    assert client.post("/api/notifications/read-all").status_code == 204
    assert client.get("/api/notifications").json()["unread"] == 0


# ── preferences ──


def test_my_settings_list_what_can_reach_me_with_mandatory_cells_locked(api_as, people):
    """UC-F4-03: security sees its alerts as required; a technician never sees them."""
    rows = api_as(people["anh"]).get("/api/notifications/preferences").json()
    alerts = {(r["event"], r["channel"]): r for r in rows if r["event"] == "security.alert"}
    assert alerts[("security.alert", "email")]["mandatory"] is True
    assert alerts[("security.alert", "email")]["enabled"] is True

    tech = api_as(people["duc"]).get("/api/notifications/preferences").json()
    assert {r["event"] for r in tech} >= {"ticket.assigned", "approval.requested"}
    assert "security.alert" not in {r["event"] for r in tech}


def test_turning_off_a_mandatory_cell_is_refused(api_as, people, glass_user):
    """AC-F4-03: anh.lh can't turn off security.alert email, and a break-glass sign-in
    reaches her on both channels."""
    response = put(
        api_as(people["anh"]),
        "/api/notifications/preferences",
        [{"event": "security.alert", "channel": "email", "enabled": False}],
    )

    assert response.status_code == 409
    assert response.json()["code"] == "mandatory_cell"

    signed_in = Client().post(
        "/api/auth/login",
        json.dumps({"username": "glass", "password": "x"}),
        content_type=JSON,
        HTTP_X_AUTH_CLIENT="admin",
    )
    assert signed_in.status_code == 200
    channels = Message.objects.filter(user=people["anh"], event="identity.break_glass_used")
    assert sorted(channels.values_list("channel", flat=True)) == ["email", "in_app"]


def test_my_settings_say_how_each_event_reaches_me(api_as, people):
    rows = api_as(people["duc"]).get("/api/notifications/preferences").json()

    reassigned = next(r for r in rows if r["event"] == "ticket.reassigned")
    assert reassigned["via"] == ["assignee", "previous_assignee"]


def test_choosing_english_changes_my_next_notice(api_as, people, ticket):
    """BR-F4-07: the language a user picks is the one their notices are written in."""
    response = put(api_as(people["duc"]), "/api/notifications/language", {"language": "en"})

    assert response.json() == {"language": "en"}
    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])
    notice = Message.objects.get(user=people["duc"], channel="in_app")
    assert notice.subject.startswith("Assigned to you: TKT-")
    assert AuditLog.objects.filter(event="account_language_changed").count() == 1


def test_saving_preferences_applies_and_is_audited(api_as, people):
    response = put(
        api_as(people["duc"]),
        "/api/notifications/preferences",
        [{"event": "ticket.assigned", "channel": "email", "enabled": False}],
    )

    assert response.status_code == 200
    row = next(
        r for r in response.json() if (r["event"], r["channel"]) == ("ticket.assigned", "email")
    )
    assert row["enabled"] is False and row["default_on"] is True
    assert AuditLog.objects.filter(event="notif_preferences_changed").count() == 1


def test_a_preference_for_an_unknown_event_is_refused(api_as, people):
    response = put(
        api_as(people["duc"]),
        "/api/notifications/preferences",
        [{"event": "ticket.liked", "channel": "email", "enabled": False}],
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_event"


# ── the matrix ──


def test_a_manager_reads_the_matrix_and_cannot_change_it(api_as, people):
    client = api_as(people["huy"])

    cells = client.get("/api/notifications/matrix").json()
    assert {"event": "approval.requested", "channel": "in_app"}.items() <= next(
        c for c in cells if c["event"] == "approval.requested" and c["channel"] == "in_app"
    ).items()

    response = put(
        client,
        "/api/notifications/matrix",
        {
            "changes": [
                {
                    "event": "ticket.assigned",
                    "recipient_kind": "assignee",
                    "channel": "email",
                    "default_on": False,
                }
            ],
            "reason": "too much mail",
        },
    )
    assert response.status_code == 403


def test_an_employee_cannot_read_the_matrix(api_as, people):
    assert api_as(people["lan"]).get("/api/notifications/matrix").status_code == 403


def test_a_workflow_admin_changes_a_default_with_a_reason(api_as, people):
    """UC-F4-04: audited notif_matrix_changed with before and after."""
    response = put(
        api_as(people["tu"]),
        "/api/notifications/matrix",
        {
            "changes": [
                {
                    "event": "ticket.assigned",
                    "recipient_kind": "assignee",
                    "channel": "email",
                    "default_on": False,
                }
            ],
            "reason": "Đội mạng chỉ cần thông báo trong ứng dụng",
        },
    )

    assert response.status_code == 200
    assert matrix_cell("ticket.assigned", "assignee", "email").default_on is False
    (audit,) = AuditLog.objects.filter(event="notif_matrix_changed")
    assert audit.payload["changes"] == [
        {
            "event": "ticket.assigned",
            "recipient_kind": "assignee",
            "channel": "email",
            "before": True,
            "after": False,
        }
    ]
    assert audit.actor_id == people["tu"].id


def test_a_matrix_change_without_a_reason_is_refused(api_as, people):
    response = put(
        api_as(people["tu"]),
        "/api/notifications/matrix",
        {
            "changes": [
                {
                    "event": "ticket.assigned",
                    "recipient_kind": "assignee",
                    "channel": "email",
                    "default_on": False,
                }
            ],
            "reason": "  ",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "reason_required"


def test_a_mandatory_matrix_cell_cannot_be_turned_off(api_as, people):
    response = put(
        api_as(people["tu"]),
        "/api/notifications/matrix",
        {
            "changes": [
                {
                    "event": "approval.requested",
                    "recipient_kind": "approver",
                    "channel": "in_app",
                    "default_on": False,
                }
            ],
            "reason": "quiet",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "mandatory_cell"
    assert matrix_cell("approval.requested", "approver", "in_app").default_on is True


def test_an_event_outside_the_catalog_is_refused(api_as, people):
    """AC-F4-10: 422 unknown_event and the matrix unchanged, even with a valid change beside it."""
    before = list(
        MatrixRule.objects.values_list("event", "recipient_kind", "channel", "default_on")
    )

    response = put(
        api_as(people["tu"]),
        "/api/notifications/matrix",
        {
            "changes": [
                {
                    "event": "ticket.assigned",
                    "recipient_kind": "assignee",
                    "channel": "email",
                    "default_on": False,
                },
                {
                    "event": "ticket.liked",
                    "recipient_kind": "assignee",
                    "channel": "in_app",
                    "default_on": True,
                },
            ],
            "reason": "likes",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_event"
    after = list(MatrixRule.objects.values_list("event", "recipient_kind", "channel", "default_on"))
    assert after == before


# ── deliveries ──


@override_settings(EMAIL_BACKEND="apps.notifications.tests.conftest.RejectingRelay")
def test_a_manager_lists_failed_deliveries_and_retries_them(api_as, people, ticket, queue):
    """UC-F4-05: retried rows are queued again, with a fresh set of attempts, audited."""
    from apps.notifications.utils.dispatcher import dispatcher

    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])
    email = Message.objects.get(user=people["duc"], channel="email")
    dispatcher.dispatch(email.id)
    client = api_as(people["huy"])

    listed = client.get("/api/notifications/deliveries?state=failed").json()
    assert [d["id"] for d in listed["items"]] == [str(email.id)]
    assert listed["items"][0]["recipient"] == "duc.tm"
    assert listed["items"][0]["last_error"].startswith("send_refused")

    response = post(client, "/api/notifications/deliveries/retry", {"all_failed": True})

    assert response.json() == {"requeued": 1}
    email.refresh_from_db()
    assert (email.state, email.attempts) == (MessageState.QUEUED.value, 0)
    assert AuditLog.objects.filter(event="notif_delivery_retried").count() == 1


def test_a_technician_cannot_see_deliveries(api_as, people):
    assert api_as(people["duc"]).get("/api/notifications/deliveries").status_code == 403


# ── webhooks ──


HOOK = {
    "name": "n8n SLA",
    "url": "http://localhost:5678/webhook/sla",
    "events": ["sla.breached"],
    "secret": "a-long-enough-secret",
}


def test_a_webhook_to_a_disallowed_host_is_refused(api_as, people):
    """AC-F4-07."""
    response = post(
        api_as(people["tu"]),
        "/api/notifications/webhooks",
        {**HOOK, "url": "https://evil.example.com/hook"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "webhook_host_refused"
    assert not WebhookSubscription.objects.exists()


def test_a_webhook_subscription_never_returns_its_secret(api_as, people):
    client = api_as(people["tu"])

    created = post(client, "/api/notifications/webhooks", HOOK)

    assert created.status_code == 201
    assert "secret" not in json.dumps(created.json())
    assert "a-long-enough-secret" not in json.dumps(
        client.get("/api/notifications/webhooks").json()
    )
    (audit,) = AuditLog.objects.filter(event="notif_webhook_created")
    assert "a-long-enough-secret" not in json.dumps(audit.payload)


def test_a_webhook_is_paused_and_deleted_with_audit(api_as, people):
    client = api_as(people["tu"])
    created = post(client, "/api/notifications/webhooks", HOOK).json()

    paused = client.patch(
        f"/api/notifications/webhooks/{created['id']}",
        json.dumps({"is_active": False}),
        content_type=JSON,
    )
    assert paused.json()["is_active"] is False
    assert client.delete(f"/api/notifications/webhooks/{created['id']}").status_code == 204
    assert not WebhookSubscription.objects.exists()
    events = set(AuditLog.objects.values_list("event", flat=True))
    assert {"notif_webhook_updated", "notif_webhook_deleted"} <= events


def test_a_webhook_for_an_unknown_event_is_refused(api_as, people):
    response = post(api_as(people["tu"]), "/api/notifications/webhooks", {**HOOK, "events": ["x"]})

    assert response.json()["code"] == "unknown_event"


def test_only_a_workflow_admin_manages_webhooks(api_as, people):
    assert api_as(people["huy"]).get("/api/notifications/webhooks").status_code == 403


# ── templates ──


def test_a_template_naming_an_unknown_variable_is_refused(api_as, people):
    response = put(
        api_as(people["tu"]),
        "/api/notifications/templates/ticket.assigned/email/vi",
        {"subject_template": "{{ticket.raw_body}}", "body_template": "x"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_variable"
    assert response.json()["details"] == {"unknown": ["ticket.raw_body"]}
    assert not Template.objects.exists()


def test_an_edited_template_is_used_for_the_next_notice(api_as, people, ticket):
    client = api_as(people["tu"])
    assert client.get("/api/notifications/templates/ticket.assigned/in_app/vi").json()["is_default"]

    saved = put(
        client,
        "/api/notifications/templates/ticket.assigned/in_app/vi",
        {"subject_template": "Việc mới: {{ticket.id}}", "body_template": "{{ticket.subject}}"},
    )
    assert saved.status_code == 200 and saved.json()["is_default"] is False

    assign_to(ticket, User.objects.get(username="duc.tm"), people["huy"])
    notice = Message.objects.get(user=people["duc"], channel="in_app")
    assert notice.subject == "Việc mới: TKT-2026-000412"
    assert AuditLog.objects.filter(event="notif_template_changed").count() == 1


def test_every_notification_route_is_gated(api_as, people):
    """BR-X-02: an employee reaches only their own inbox and preferences."""
    client = api_as(User.objects.create_user(username="e2", password="x", role=UserRole.EMPLOYEE))
    assert client.get("/api/notifications").status_code == 200
    assert client.get("/api/notifications/preferences").status_code == 200
    for url in (
        "/api/notifications/matrix",
        "/api/notifications/deliveries",
        "/api/notifications/webhooks",
        "/api/notifications/templates/ticket.assigned/email/vi",
    ):
        assert client.get(url).status_code == 403, url
