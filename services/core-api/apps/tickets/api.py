"""
Ticket endpoints. `submit_ticket` is the one HTTP-facing place masking runs
inline and synchronously (spec §5); the contract for what is written before
it returns lives in services/submission.py.
"""

from __future__ import annotations

from typing import Any

from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from pydantic import ValidationError as PydanticValidationError

from contracts.ticket import TicketIn

from apps.tickets.models import Ticket
from apps.tickets.schemas import TicketSubmitIn
from apps.tickets.services.submission import ticket_submit
from common.permissions import AuthedRequest

router = Router(tags=["tickets"])


@router.post("/submit", auth=JWTAuth())
def submit_ticket(request: AuthedRequest, payload: TicketSubmitIn) -> dict[str, Any]:
    try:
        ticket_in = TicketIn(**payload.dict())
    except PydanticValidationError as e:
        raise HttpError(422, e.json()) from e

    ticket = ticket_submit(
        reporter=request.auth, ticket_in=ticket_in, trace_id=getattr(request, "trace_id", None)
    )
    return {
        "ticket_public_id": ticket.public_id,
        "status": ticket.status,
        "pii_level": ticket.pii_level,
    }


@router.get("/{public_id}", auth=JWTAuth())
def get_ticket(request: AuthedRequest, public_id: str) -> dict[str, Any]:
    try:
        t = Ticket.objects.get(public_id=public_id)
    except Ticket.DoesNotExist as e:
        raise HttpError(404, "ticket not found") from e
    return {
        "public_id": t.public_id,
        "subject_masked": t.subject_masked,
        "body_masked": t.body_masked,
        "pii_level": t.pii_level,
        "status": t.status,
        "category": t.category,
        "created_at": t.created_at.isoformat(),
    }
