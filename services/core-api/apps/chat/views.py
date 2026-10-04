"""
The requester's chat. A question is submitted as a ticket (masked inline,
then the usual pipeline); the chat polls for the outcome and, when the
outcome is a handoff to support, asks the requester before carrying it out
(`pipeline.waits_for_requester`). Every endpoint sees only the caller's own
chat tickets.
"""

from __future__ import annotations

from django.db.models import QuerySet
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.accounts.permissions import AuthedRequest
from apps.chat.request_schema import ChatAskIn
from apps.chat.response_schema import ChatTurnOut
from apps.chat.utils import chat_turn, ticket_in_from_message
from apps.tickets.models import Ticket, TicketSource
from apps.tickets.utils.pipeline import NotAwaitingRequester, release_to_support

router = Router(tags=["chat"])


def _own_chat_tickets(request: AuthedRequest) -> QuerySet[Ticket]:
    return Ticket.objects.filter(reporter=request.auth, source=TicketSource.CHAT.value)


def _own_chat_ticket(request: AuthedRequest, public_id: str) -> Ticket:
    # Someone else's ticket is a 404, not a 403: it does not say it exists.
    ticket = _own_chat_tickets(request).filter(public_id=public_id).first()
    if ticket is None:
        raise HttpError(404, "conversation not found")
    return ticket


@router.post("/ask", auth=JWTAuth(), response=ChatTurnOut)
def ask(request: AuthedRequest, payload: ChatAskIn) -> ChatTurnOut:
    ticket = Ticket.objects.submit(
        reporter=request.auth,
        ticket_in=ticket_in_from_message(payload.message),
        trace_id=getattr(request, "trace_id", None),
        source=TicketSource.CHAT,
    )
    return chat_turn(ticket)


@router.get("/tickets", auth=JWTAuth(), response=list[ChatTurnOut])
def history(request: AuthedRequest) -> list[ChatTurnOut]:
    return [chat_turn(t) for t in _own_chat_tickets(request).order_by("created_at")]


@router.get("/tickets/{public_id}", auth=JWTAuth(), response=ChatTurnOut)
def turn(request: AuthedRequest, public_id: str) -> ChatTurnOut:
    return chat_turn(_own_chat_ticket(request, public_id))


@router.post("/tickets/{public_id}/create-ticket", auth=JWTAuth(), response=ChatTurnOut)
def create_ticket(request: AuthedRequest, public_id: str) -> ChatTurnOut:
    ticket = _own_chat_ticket(request, public_id)
    try:
        ticket = release_to_support(ticket.id, request.auth.id, getattr(request, "trace_id", None))
    except NotAwaitingRequester as e:
        raise HttpError(409, "this question is not waiting for a ticket") from e
    return chat_turn(ticket)
