"""A requester's chat conversation: the turns whose masked text a new turn may carry (F3, ADR-0034)."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class ConversationState(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class EndReason(StrEnum):
    IDLE = "idle"
    USER = "user"
    BLOCKED = "blocked"
    MASK_FAILED = "mask_failed"
    # Building the earlier turns failed; the ticket was analysed alone (ADR-0034).
    CONTEXT_FAILED = "context_failed"


class ConversationQuerySet(models.QuerySet["Conversation"]):
    def active(self) -> ConversationQuerySet:
        return self.filter(state=ConversationState.ACTIVE.value)

    def idle_since(self, cutoff: datetime) -> ConversationQuerySet:
        """Active conversations whose last turn is older than `cutoff`."""
        return self.active().filter(last_activity_at__lt=cutoff)


class Conversation(BaseModel):
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="conversations"
    )
    state = models.CharField(
        max_length=10,
        choices=[(s.value, s.value) for s in ConversationState],
        default=ConversationState.ACTIVE.value,
    )
    started_at = models.DateTimeField()
    last_activity_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(
        max_length=20, choices=[(r.value, r.value) for r in EndReason], null=True, blank=True
    )

    objects = ConversationQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "chat_conversations"
        constraints = [
            models.UniqueConstraint(
                fields=["requester"],
                condition=models.Q(state="active"),
                name="chat_conversations_one_active",
            ),
        ]

    def is_open_at(self, now: datetime, idle_minutes: int) -> bool:
        """Whether a turn at `now` still belongs to this conversation (BR-F3-02)."""
        return self.state == ConversationState.ACTIVE.value and now - self.last_activity_at < (
            timedelta(minutes=idle_minutes)
        )
