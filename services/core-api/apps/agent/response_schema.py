"""Response bodies for the agent's routes (F15 §h.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema

from apps.accounts.models import Language
from apps.agent.domain.vocabulary import CHECKED_GOES_WITH_TICKET, OPEN_TICKET, TICKET_OPENED
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
from apps.infra.response_schema import InfraQueryReceiptOut
from apps.infra.services.recording import missing_sources


class AgentReceiptOut(Schema):
    """What one of the turn's write calls did, from its HTTP result (BR-F15-12)."""

    tool: str
    outcome: Literal[
        "done", "awaiting_confirmation", "draft_waiting", "refused", "failed", "unknown"
    ]
    method: str
    path: str
    action_id: uuid.UUID | None
    chat_turn: str | None = None


class AgentChoiceOut(Schema):
    """One button of a reply's choice card; pressing it sends `label` as the next message."""

    kind: str
    id: str | None
    label: str


class AgentNeedsStaffOut(Schema):
    """What code adds after the model's text when a turn hands off on purpose, in the message's
    language (BR-F15-24)."""

    # The line for a turn that read something before it handed off.
    checked: str | None
    # The "Open a ticket" button, while the turn offers one.
    button: str
    # The reply once the ticket is open.
    opened: str | None

    @classmethod
    def of(cls, turn: AgentTurn) -> AgentNeedsStaffOut:
        language = turn.language()
        ticket = turn.handoff_ticket
        return cls(
            checked=CHECKED_GOES_WITH_TICKET[language] if turn.ran_a_read() else None,
            button=OPEN_TICKET[language],
            opened=TICKET_OPENED[language].format(ticket=ticket.public_id) if ticket else None,
        )


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
    ticket_offered: bool = False
    # The reply's choice card, "Something else" last (BR-F15-22).
    choices: list[AgentChoiceOut] = []
    needs_staff: AgentNeedsStaffOut | None = None
    queued_at: datetime
    finished_at: datetime | None
    queries: list[InfraQueryReceiptOut] = []
    warnings: list[str] = []
    # The language of the turn's reply, choices, hand-off text and warnings.
    language: Language

    @classmethod
    def of(cls, turn: AgentTurn) -> AgentTurnOut:
        queries = list(turn.infra_queries.all())
        staff = turn.conversation.surface == AgentSurface.CONSOLE.value
        language = turn.language()
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
            ticket_offered=turn.offers_ticket(),
            choices=[AgentChoiceOut(**c) for c in turn.choices or []],
            needs_staff=AgentNeedsStaffOut.of(turn) if turn.needs_staff() else None,
            queued_at=turn.queued_at,
            finished_at=turn.finished_at,
            queries=[InfraQueryReceiptOut.of(q, staff=staff) for q in queries],
            warnings=missing_sources(queries, language),
            language=language,
        )


class AgentConversationSummaryOut(Schema):
    """One line of a person's conversation history."""

    conversation_id: uuid.UUID
    state: AgentConversationState
    end_reason: str
    first_message: str
    turns: int
    last_activity_at: datetime

    @classmethod
    def of(cls, conversation: AgentConversation) -> AgentConversationSummaryOut:
        return cls(
            conversation_id=conversation.id,
            state=AgentConversationState(conversation.state),
            end_reason=conversation.end_reason,
            first_message=getattr(conversation, "first_message", "") or "",
            turns=getattr(conversation, "turn_count", 0),
            last_activity_at=conversation.last_activity_at,
        )


class AgentConversationOut(Schema):
    conversation_id: uuid.UUID
    surface: AgentSurface
    state: AgentConversationState
    end_reason: str
    turns: list[AgentTurnOut]

    @classmethod
    def of(cls, conversation: AgentConversation) -> AgentConversationOut:
        turns = conversation.turns.with_receipts().order_by("seq")
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
