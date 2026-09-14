"""
Ticket submission endpoint. This is the one HTTP-facing place masking runs
inline and synchronously (spec §5) — by the time this handler returns, the
`tickets` row committed to the database contains ONLY masked content;
`pii_quarantine` holds the encrypted raw values, and the AI pipeline is
handed off to Celery for everything downstream (retrieval, LLM, routing).
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from django.db import transaction
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from pydantic import ValidationError as PydanticValidationError

from contracts.ticket import TicketIn

from apps.audit.services import audit
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.services.crypto import build_quarantine_entries
from apps.tickets.services.ids import next_ticket_public_id
from apps.tickets.services.masking import mask

router = Router(tags=["tickets"])


class TicketSubmitIn(Schema):
    """Django Ninja's own input schema for body binding — a plain `dict`
    parameter doesn't bind the JSON request body the way a Schema/pydantic
    model does. `contracts.ticket.TicketIn` (the real domain contract,
    with its length constraints) is still what actually validates the
    submission below; this class only exists to get the raw JSON off the
    wire correctly."""

    subject: str
    body: str
    attachments: list[str] = []


@router.post("/submit", auth=JWTAuth())
def submit_ticket(request, payload: TicketSubmitIn):
    try:
        ticket_in = TicketIn(**payload.dict())
    except PydanticValidationError as e:
        raise HttpError(422, e.json()) from e

    result = async_to_sync(mask)(ticket_in)
    quarantine_entries = build_quarantine_entries(result.placeholder_map)

    with transaction.atomic():
        ticket = Ticket.objects.create(
            public_id=next_ticket_public_id(),
            reporter=request.auth,
            subject_masked=result.subject_masked,
            body_masked=result.body_masked,
            pii_level=result.pii_level.value,
            pii_map={ph: str(entry.ref) for ph, entry in quarantine_entries.items()},
        )
        PiiQuarantine.objects.bulk_create(
            [
                PiiQuarantine(
                    ref=entry.ref,
                    ticket=ticket,
                    ciphertext=entry.ciphertext,
                    nonce=entry.nonce,
                    expires_at=entry.expires_at,
                )
                for entry in quarantine_entries.values()
            ]
        )
        audit(
            "ticket_submitted",
            actor_type="human",
            actor_id=request.auth.id,
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "pii_level": ticket.pii_level,
                "trace_id": getattr(request, "trace_id", None),
            },
            trace_id=getattr(request, "trace_id", None),
        )

    from apps.tickets.tasks import process_ticket

    process_ticket.delay(ticket.id)

    return {
        "ticket_public_id": ticket.public_id,
        "status": ticket.status,
        "pii_level": ticket.pii_level,
    }


@router.get("/{public_id}", auth=JWTAuth())
def get_ticket(request, public_id: str):
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
