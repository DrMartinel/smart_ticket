"""Notifications (F4, ADR-0033): the matrix, preferences, messages, webhook subscriptions, templates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q, QuerySet

from apps.core.models import BaseModel
from apps.notifications.utils.vocabulary import Channel, MessageState


def _choices(enum: Any) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class MatrixRule(BaseModel):
    """Whether one recipient kind gets one event on one channel by default."""

    event = models.CharField(max_length=64)
    recipient_kind = models.CharField(max_length=32)
    channel = models.CharField(max_length=10, choices=_choices(Channel))
    default_on = models.BooleanField(default=True)
    # Copied from the catalog for display; decisions read the catalog.
    mandatory = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "notif_matrix_rules"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "recipient_kind", "channel"], name="uniq_notif_matrix_cell"
            )
        ]
        ordering = ["event", "recipient_kind", "channel"]


class Preference(BaseModel):
    """One user's choice for one event on one channel."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notif_preferences"
    )
    event = models.CharField(max_length=64)
    channel = models.CharField(max_length=10, choices=_choices(Channel))
    enabled = models.BooleanField()

    class Meta(BaseModel.Meta):
        db_table = "notif_preferences"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event", "channel"], name="uniq_notif_preference"
            )
        ]


class MessageQuerySet(QuerySet["Message"]):
    def inbox(self, user: Any) -> MessageQuerySet:
        """`user`'s delivered in-app notices, newest first."""
        return self.filter(
            user=user, channel=Channel.IN_APP.value, state=MessageState.DELIVERED.value
        ).order_by("-created_at", "-id")

    def deliveries(self) -> MessageQuerySet:
        """Messages a person may need to look at: every email and webhook, and failed in-app ones."""
        return (
            self.filter(~Q(channel=Channel.IN_APP.value) | Q(state=MessageState.FAILED.value))
            .select_related("user", "subscription", "ticket")
            .order_by("-created_at", "-id")
        )

    def matching(
        self,
        *,
        state: str | None = None,
        channel: str | None = None,
        event: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> MessageQuerySet:
        """The messages a delivery-log filter selects."""
        rows = self
        if state:
            rows = rows.filter(state=state)
        if channel:
            rows = rows.filter(channel=channel)
        if event:
            rows = rows.filter(event=event)
        if since:
            rows = rows.filter(created_at__gte=since)
        if until:
            rows = rows.filter(created_at__lt=until)
        return rows

    def due(self, now: datetime) -> MessageQuerySet:
        """Queued messages whose next attempt is due."""
        return self.filter(state=MessageState.QUEUED.value).filter(
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
        )


class Message(BaseModel):
    """One notice to one user or webhook subscription on one channel."""

    event_id = models.UUIDField()
    event = models.CharField(max_length=64)
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    subscription = models.ForeignKey(
        "notifications.WebhookSubscription",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
    )
    channel = models.CharField(max_length=10, choices=_choices(Channel))
    language = models.CharField(max_length=5, blank=True, default="")
    subject = models.CharField(max_length=255)
    body = models.TextField()
    link = models.CharField(max_length=500, blank=True, default="")
    state = models.CharField(max_length=10, choices=_choices(MessageState))
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    objects = MessageQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "notif_messages"
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False, subscription__isnull=True)
                | Q(user__isnull=True, subscription__isnull=False),
                name="notif_message_one_recipient",
            ),
            models.UniqueConstraint(
                fields=["event_id", "user", "subscription", "channel"],
                name="uniq_notif_message",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["user", "read_at", "created_at"], name="notif_msg_inbox"),
            models.Index(fields=["state", "next_attempt_at"], name="notif_msg_due"),
        ]

    def recipient_name(self) -> str:
        if self.user is not None:
            return self.user.username
        return self.subscription.name if self.subscription is not None else ""


class WebhookSubscription(BaseModel):
    """An external system that gets signed JSON for the events it names (BR-F4-06)."""

    name = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    events = ArrayField(models.CharField(max_length=64))
    secret_ciphertext = models.BinaryField()
    secret_nonce = models.BinaryField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "notif_webhook_subscriptions"
        ordering = ["name"]


class Template(BaseModel):
    """An edited subject and body for one event, channel and language, in place of the default."""

    event = models.CharField(max_length=64)
    channel = models.CharField(max_length=10, choices=_choices(Channel))
    language = models.CharField(max_length=5)
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "notif_templates"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "channel", "language"], name="uniq_notif_template"
            )
        ]
