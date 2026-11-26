"""
The agent's own routes (F15 §h.2): a message to the agent, its turns and conversations, and the
actions it left the user. An agent cannot call any of them.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from ninja import Router, Status

from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.accounts.domain.catalog import Permission
from apps.agent.models import (
    AgentAction,
    AgentActionKind,
    AgentActionState,
    AgentConversation,
    AgentTargetKind,
    AgentTurn,
)
from apps.agent.request_schema import AgentTurnIn
from apps.agent.response_schema import (
    AgentActionOut,
    AgentConversationOut,
    AgentConversationSummaryOut,
    AgentTurnOut,
)
from apps.agent.services.turns import agent_turns
from apps.agent.domain.vocabulary import AgentError, AgentRefusal

router = Router(tags=["agent"])


@router.post("/turns", auth=SessionAuth(), response={202: AgentTurnOut})
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def start_turn(request: AuthedRequest, payload: AgentTurnIn) -> Status[AgentTurnOut]:
    turn = agent_turns.start(
        request.auth, payload.message, payload.surface, payload.conversation_id
    )
    return Status(202, AgentTurnOut.of(AgentTurn.objects.with_receipts().get(id=turn.id)))


@router.get("/turns/{turn_id}", auth=SessionAuth(), response=AgentTurnOut)
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def turn(request: AuthedRequest, turn_id: uuid.UUID) -> AgentTurnOut:
    found = AgentTurn.objects.of_user(request.auth.user).with_receipts().filter(id=turn_id).first()
    if found is None:
        raise AgentError(404, AgentRefusal.CONVERSATION_NOT_FOUND, "no such turn")
    return AgentTurnOut.of(found)


@router.post("/turns/{turn_id}/ticket", auth=SessionAuth(), response=AgentTurnOut)
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def open_ticket(request: AuthedRequest, turn_id: uuid.UUID) -> AgentTurnOut:
    opened = agent_turns.open_ticket(request.auth.user, turn_id)
    return AgentTurnOut.of(AgentTurn.objects.with_receipts().get(id=opened.id))


@router.get("/conversations", auth=SessionAuth(), response=list[AgentConversationSummaryOut])
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def conversations(request: AuthedRequest) -> list[AgentConversationSummaryOut]:
    """The user's own conversations, newest first."""
    rows = (
        AgentConversation.objects.of_user(request.auth.user)
        .summarised()
        .order_by("-last_activity_at")[: settings.THRESHOLDS.agent.history_limit]
    )
    return [AgentConversationSummaryOut.of(c) for c in rows]


@router.get("/conversations/{conversation_id}", auth=SessionAuth(), response=AgentConversationOut)
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def conversation(request: AuthedRequest, conversation_id: uuid.UUID) -> AgentConversationOut:
    found = AgentConversation.objects.of_user(request.auth.user).filter(id=conversation_id).first()
    if found is None:
        raise AgentError(404, AgentRefusal.CONVERSATION_NOT_FOUND, "no such conversation")
    return AgentConversationOut.of(found)


@router.post("/conversations/{conversation_id}/end", auth=SessionAuth(), response={204: None})
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def end_conversation(request: AuthedRequest, conversation_id: uuid.UUID) -> Status[None]:
    agent_turns.end_by_user(request.auth.user, conversation_id)
    return Status(204, None)


@router.get("/actions", auth=SessionAuth(), response=list[AgentActionOut])
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def actions(
    request: AuthedRequest,
    state: AgentActionState | None = None,
    kind: AgentActionKind | None = None,
    ticket: str | None = None,
    review_item: uuid.UUID | None = None,
    target_kind: AgentTargetKind | None = None,
    target_ref: str | None = None,
) -> list[AgentActionOut]:
    """The user's actions, newest first, narrowed to a state, kind, ticket, review item or
    target."""
    rows = AgentAction.objects.of_user(request.auth.user).narrowed(
        state, kind, ticket, review_item, target_kind, target_ref
    )
    return [AgentActionOut.of(a) for a in rows]


@router.post("/actions/{action_id}/dismiss", auth=SessionAuth(), response={204: None})
@require(Permission.AGENT_USE, agent=AgentTier.NONE)
def dismiss(request: AuthedRequest, action_id: uuid.UUID) -> Status[None]:
    agent_turns.dismiss(request.auth.user, action_id)
    return Status(204, None)
