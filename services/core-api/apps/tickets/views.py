"""
Ticket endpoints. `submit_ticket` is the one HTTP-facing place masking runs
inline and synchronously (spec §5); the contract for what is written before
it returns lives in `TicketManager.submit` (models.py).
"""

from __future__ import annotations

from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from pydantic import ValidationError as PydanticValidationError

from contracts.ticket import TicketIn

from apps.tickets.models import Ticket
from apps.tickets.request_schema import TicketSubmitIn
from apps.tickets.response_schema import TicketOut, TicketSubmitOut
from common.permissions import AuthedRequest

router = Router(tags=["tickets"])


@router.post("/submit", auth=JWTAuth(), response=TicketSubmitOut)
def submit_ticket(request: AuthedRequest, payload: TicketSubmitIn) -> Ticket:
    try:
        ticket_in = TicketIn(**payload.dict())
    except PydanticValidationError as e:
        raise HttpError(422, e.json()) from e

    return Ticket.objects.submit(
        reporter=request.auth, ticket_in=ticket_in, trace_id=getattr(request, "trace_id", None)
    )


@router.get("/{public_id}", auth=JWTAuth(), response=TicketOut)
def get_ticket(request: AuthedRequest, public_id: str) -> Ticket:
    try:
        return Ticket.objects.get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
