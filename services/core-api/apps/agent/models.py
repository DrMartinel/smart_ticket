"""What an agent turn leaves for a person: a call waiting for the user's confirmation, or a draft a
person applies (F15, ADR-0046)."""

from __future__ import annotations

from enum import StrEnum

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


# The longest concrete path an agent action can hold.
PATH_MAX_LENGTH = 300


class AgentActionKind(StrEnum):
    CONFIRM = "confirm"
    DRAFT = "draft"


class AgentActionState(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class AgentAction(BaseModel):
    """One route call an agent made on a `confirm` or `human_only` route, held for a person."""

    kind = models.CharField(max_length=10, choices=_choices(AgentActionKind))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_actions"
    )
    conversation_id = models.UUIDField()
    turn_id = models.UUIDField(db_index=True)
    tool = models.CharField(max_length=40, blank=True, default="")
    method = models.CharField(max_length=8)
    route = models.CharField(max_length=200)
    path = models.CharField(max_length=PATH_MAX_LENGTH)
    arguments = models.JSONField()
    arguments_sha256 = models.CharField(max_length=64)
    target_kind = models.CharField(max_length=20, blank=True, default="")
    target_ref = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(
        max_length=12, choices=_choices(AgentActionState), default=AgentActionState.PENDING.value
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(BaseModel.Meta):
        db_table = "agent_actions"
        indexes = [
            models.Index(fields=["user", "state"]),
            models.Index(fields=["target_kind", "target_ref", "state"]),
        ]
