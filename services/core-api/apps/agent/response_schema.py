"""Response bodies for the agent's routes (F15 §h.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema

from apps.agent.models import (
    AgentAction,
    AgentActionKind,
    AgentActionState,
    AgentConversation,
    AgentConversationState,
    AgentSurface,
    AgentTurn,
    AgentTurnState,
)


class AgentReceiptOut(Schema):
    """What one of the turn's write calls did, from its HTTP result (BR-F15-12)."""

    tool: str
    outcome: Literal[
        "done", "awaiting_confirmation", "draft_waiting", "refused", "failed", "unknown"
    ]
    method: str
    path: str
    action_id: uuid.UUID | None


class AgentTurnOut(Schema):
    turn_id: uuid.UUID
    conversation_id: uuid.UUID
    seq: int
    message_masked: str
    state: AgentTurnState
    reply: str
    receipts: list[AgentReceiptOut]
    stop_reason: str | None
    handoff_ticket: str | None
    queued_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, turn: AgentTurn) -> AgentTurnOut:
        return cls(
            turn_id=turn.id,
            conversation_id=turn.conversation_id,
            seq=turn.seq,
            message_masked=turn.message_masked,
            state=AgentTurnState(turn.state),
            reply=turn.reply_text,
            receipts=[AgentReceiptOut(**r) for r in turn.receipts],
            stop_reason=turn.stop_reason,
            handoff_ticket=turn.handoff_ticket.public_id if turn.handoff_ticket else None,
            queued_at=turn.queued_at,
            finished_at=turn.finished_at,
        )


class AgentConversationOut(Schema):
    conversation_id: uuid.UUID
    surface: AgentSurface
    state: AgentConversationState
    end_reason: str
    turns: list[AgentTurnOut]

    @classmethod
    def of(cls, conversation: AgentConversation) -> AgentConversationOut:
        turns = conversation.turns.select_related("handoff_ticket").order_by("seq")
        return cls(
            conversation_id=conversation.id,
            surface=AgentSurface(conversation.surface),
            state=AgentConversationState(conversation.state),
            end_reason=conversation.end_reason,
            turns=[AgentTurnOut.of(t) for t in turns],
        )


class AgentActionOut(Schema):
    action_id: uuid.UUID
    kind: AgentActionKind
    state: AgentActionState
    tool: str
    method: str
    route: str
    path: str
    arguments: dict[str, object]
    target_kind: str
    target_ref: str
    created_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, action: AgentAction) -> AgentActionOut:
        return cls(
            action_id=action.id,
            kind=AgentActionKind(action.kind),
            state=AgentActionState(action.state),
            tool=action.tool,
            method=action.method,
            route=action.route,
            path=action.path,
            arguments=action.arguments,
            target_kind=action.target_kind,
            target_ref=action.target_ref,
            created_at=action.created_at,
            expires_at=action.expires_at,
        )
