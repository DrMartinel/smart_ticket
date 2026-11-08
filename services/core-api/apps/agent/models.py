"""An agent conversation, its turns and their tool calls, and what a turn leaves for a person: a
call waiting for the user's confirmation, or a draft a person applies (F15, ADR-0046)."""

from __future__ import annotations

import uuid
from enum import StrEnum

from django.conf import settings
from django.db import models
from django.db.models import F

from apps.core.models import BaseModel


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


# The longest concrete path an agent action can hold.
PATH_MAX_LENGTH = 300


class AgentSurface(StrEnum):
    CHAT = "chat"
    CONSOLE = "console"


class AgentConversationState(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class AgentConversationEnd(StrEnum):
    IDLE = "idle"
    USER = "user"
    INJECTION = "injection"
    MASK_FAILED = "mask_failed"


class AgentTurnState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REPLIED = "replied"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    HANDED_OFF = "handed_off"


class AgentStepOutcome(StrEnum):
    OK = "ok"
    REFUSED = "refused"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DRAFTED = "drafted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AgentConversationQuerySet(models.QuerySet["AgentConversation"]):
    def active(self) -> AgentConversationQuerySet:
        return self.filter(state=AgentConversationState.ACTIVE.value)


class AgentConversation(BaseModel):
    """One person's exchange with the agent on one surface."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_conversations"
    )
    surface = models.CharField(max_length=10, choices=_choices(AgentSurface))
    state = models.CharField(
        max_length=10,
        choices=_choices(AgentConversationState),
        default=AgentConversationState.ACTIVE.value,
    )
    chat_conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_conversations",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(
        max_length=12, choices=_choices(AgentConversationEnd), blank=True, default=""
    )

    objects = AgentConversationQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "agent_conversations"
        indexes = [models.Index(fields=["user", "state"])]

    def is_active(self) -> bool:
        return self.state == AgentConversationState.ACTIVE.value


class AgentTurnQuerySet(models.QuerySet["AgentTurn"]):
    def unfinished(self) -> AgentTurnQuerySet:
        return self.filter(state__in=(AgentTurnState.QUEUED.value, AgentTurnState.RUNNING.value))

    def count_write(self, turn_id: uuid.UUID, cap: int) -> bool:
        """Counts one write call of the turn; False once it has made `cap` (FR-F15-015)."""
        return bool(
            self.filter(id=turn_id, write_calls__lt=cap).update(write_calls=F("write_calls") + 1)
        )


class AgentTurn(BaseModel):
    """One message to the agent and what the agent did with it."""

    conversation = models.ForeignKey(
        AgentConversation, on_delete=models.CASCADE, related_name="turns"
    )
    seq = models.PositiveIntegerField()
    message_masked = models.TextField()
    pii_level = models.CharField(max_length=20)
    pii_map = models.JSONField(default=dict)
    # The sign-in the turn's agent token is minted from (BR-F15-02).
    session_family = models.UUIDField()
    state = models.CharField(
        max_length=24, choices=_choices(AgentTurnState), default=AgentTurnState.QUEUED.value
    )
    # A ReasonCode value when the turn handed off.
    stop_reason = models.CharField(max_length=40, null=True, blank=True)
    reply_text = models.TextField(blank=True, default="")
    receipts = models.JSONField(default=list)
    tool_calls = models.PositiveIntegerField(default=0)
    write_calls = models.PositiveIntegerField(default=0)
    model = models.CharField(max_length=100, blank=True, default="")
    prompt_version = models.CharField(max_length=50, blank=True, default="")
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    handoff_ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = AgentTurnQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "agent_turns"
        constraints = [
            models.UniqueConstraint(fields=["conversation", "seq"], name="agent_turns_seq_unique")
        ]

    def is_finished(self) -> bool:
        return self.state not in (AgentTurnState.QUEUED.value, AgentTurnState.RUNNING.value)


class AgentStep(BaseModel):
    """One tool call of a turn: what was sent and what core-api answered. No result body."""

    turn = models.ForeignKey(AgentTurn, on_delete=models.CASCADE, related_name="steps")
    seq = models.PositiveIntegerField()
    tool = models.CharField(max_length=40)
    arguments_masked = models.JSONField()
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=PATH_MAX_LENGTH)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=24, choices=_choices(AgentStepOutcome))
    injection_flagged = models.BooleanField(default=False)
    action = models.ForeignKey(
        "AgentAction", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta(BaseModel.Meta):
        db_table = "agent_steps"
        constraints = [
            models.UniqueConstraint(fields=["turn", "seq"], name="agent_steps_seq_unique")
        ]


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
    conversation = models.ForeignKey(
        AgentConversation, on_delete=models.CASCADE, related_name="actions"
    )
    turn = models.ForeignKey(AgentTurn, on_delete=models.CASCADE, related_name="actions")
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
