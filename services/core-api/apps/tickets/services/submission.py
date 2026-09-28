"""
Ticket submission — spec §5. Masking runs INLINE and synchronously, inside
the submit request: by the time `ticket_submit` returns, the `tickets` row
committed to the database contains ONLY masked content, `pii_quarantine`
holds the encrypted raw values, and the AI pipeline has been handed off to
Celery for everything downstream (retrieval, LLM, routing).
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from django.db import transaction

from contracts.ticket import TicketIn

from apps.accounts.models import User
from apps.audit.services import audit
from apps.tickets import tasks
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.services.ids import next_ticket_public_id
from apps.tickets.utils.masking import mask


def ticket_submit(*, reporter: User, ticket_in: TicketIn, trace_id: str | None) -> Ticket:
    """Masks, persists and enqueues one validated submission.

    A masking failure does not raise: the ticket is stored with whatever
    regex could mask, at `PIILevel.MASK_FAILED`, which the router sends to a
    human. Callers must never retry or drop a MASK_FAILED ticket.
    """
    result = async_to_sync(mask)(ticket_in)
    quarantine_entries = build_quarantine_entries(result.placeholder_map)

    with transaction.atomic():
        ticket = Ticket.objects.create(
            public_id=next_ticket_public_id(),
            reporter=reporter,
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
            actor_id=reporter.id,
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "pii_level": ticket.pii_level,
                "trace_id": trace_id,
            },
            trace_id=trace_id,
        )

    # Outside the atomic block on purpose: enqueued before commit, a fast
    # worker can look the ticket up, get DoesNotExist, and leave it stuck at
    # status="new" with no routing decision.
    tasks.process_ticket.delay(ticket.id)
    return ticket
