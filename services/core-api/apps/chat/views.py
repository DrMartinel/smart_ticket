"""
The requester's chat. A question is submitted as a ticket (masked inline,
then the usual pipeline); the chat polls for the outcome and, when the
outcome is a handoff to support, asks the requester before carrying it out
(`pipeline.waits_for_requester`). A clarifying question is answered here
too, and the answer re-runs the pipeline (ADR-0023). Questions are grouped into conversations
whose earlier masked turns go to ai-engine with a new one (F3, ADR-0034). Every endpoint sees
only the caller's own chat tickets.
"""

from __future__ import annotations

import uuid

from django.db.models import QuerySet
from ninja import Router, Status
from ninja.errors import HttpError

from apps.accounts.permissions import ALL_ROLES, AuthedRequest, SessionAuth, require_role
from apps.chat.request_schema import ChatAskIn, ChatClarifyIn
from apps.chat.response_schema import ChatTurnOut
from apps.chat.utils.conversations import conversations
from apps.chat.utils.turns import chat_turn, ticket_in_from_message
from apps.tickets.models import Ticket, TicketSource
from apps.tickets.utils.clarification import NotAwaitingAnswer, clarifications
from apps.tickets.utils.pipeline import NotAwaitingRequester, release_to_support

router = Router(tags=["chat"])


def _own_chat_tickets(request: AuthedRequest) -> QuerySet[Ticket]:
    return Ticket.objects.filter(
        reporter=request.auth, source=TicketSource.CHAT.value
    ).select_related("workflow_status")


def _own_chat_ticket(request: AuthedRequest, public_id: str) -> Ticket:
    # Someone else's ticket is a 404, not a 403: it does not say it exists.
    ticket = _own_chat_tickets(request).filter(public_id=public_id).first()
    if ticket is None:
        raise HttpError(404, "conversation not found")
    return ticket


@router.post("/ask", auth=SessionAuth(), response=ChatTurnOut)
@require_role(*ALL_ROLES)
def ask(request: AuthedRequest, payload: ChatAskIn) -> ChatTurnOut:
    conversation = conversations.for_turn(request.auth, payload.conversation_id)
    ticket = Ticket.objects.submit(
        reporter=request.auth,
        ticket_in=ticket_in_from_message(payload.message),
        trace_id=getattr(request, "trace_id", None),
        source=TicketSource.CHAT,
        conversation=conversation,
    )
    conversations.after_submit(ticket)
    return chat_turn(ticket)


@router.post("/conversations/{conversation_id}/end", auth=SessionAuth(), response={204: None})
@require_role(*ALL_ROLES)
def end_conversation(request: AuthedRequest, conversation_id: uuid.UUID) -> Status[None]:
    conversations.end_by_requester(request.auth, conversation_id)
    return Status(204, None)


@router.get("/tickets", auth=SessionAuth(), response=list[ChatTurnOut])
@require_role(*ALL_ROLES)
def history(request: AuthedRequest, conversation_id: uuid.UUID | None = None) -> list[ChatTurnOut]:
    """The turns of one conversation: the named one, else the current one (FR-F3-004)."""
    if conversation_id is None:
        current = conversations.current(request.auth)
        if current is None:
            return []
        conversation_id = current.id
    tickets = _own_chat_tickets(request).filter(conversation_id=conversation_id)
    return [chat_turn(t) for t in tickets.order_by("created_at")]


@router.get("/tickets/{public_id}", auth=SessionAuth(), response=ChatTurnOut)
@require_role(*ALL_ROLES)
def turn(request: AuthedRequest, public_id: str) -> ChatTurnOut:
    return chat_turn(_own_chat_ticket(request, public_id))


@router.post("/tickets/{public_id}/create-ticket", auth=SessionAuth(), response=ChatTurnOut)
@require_role(*ALL_ROLES)
def create_ticket(request: AuthedRequest, public_id: str) -> ChatTurnOut:
    ticket = _own_chat_ticket(request, public_id)
    try:
        ticket = release_to_support(ticket.id, request.auth.id, getattr(request, "trace_id", None))
    except NotAwaitingRequester as e:
        raise HttpError(409, "this question is not waiting for a ticket") from e
    return chat_turn(ticket)


@router.post("/tickets/{public_id}/clarify", auth=SessionAuth(), response=ChatTurnOut)
@require_role(*ALL_ROLES)
def clarify(request: AuthedRequest, public_id: str, payload: ChatClarifyIn) -> ChatTurnOut:
    ticket = _own_chat_ticket(request, public_id)
    try:
        ticket = clarifications.answer(
            ticket.id, request.auth.id, payload.answer, getattr(request, "trace_id", None)
        )
    except NotAwaitingAnswer as e:
        raise HttpError(409, "this question is no longer waiting for an answer") from e
    return chat_turn(ticket)
