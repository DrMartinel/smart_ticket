"""
Asks a live chat ticket's requester which shown page they mean, and takes
their answer (ADR-0023).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.kb.models import KbArticle
from apps.tickets.models import AiRun, PiiQuarantine, Ticket, TicketClarification
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.utils.masking import mask_reply
from apps.tickets.utils.patterns import PIILevel

if TYPE_CHECKING:
    from config.settings.base import ClarificationThresholds

# The question every clarifying chat ticket asks (ADR-0023, amended 2026-10-13).
CLARIFY_QUESTION = "Which of these is closest to what you need?"

# Marks the requester's answer in the ticket body; `propose.v9` names it.
CLARIFIED_LABEL = "Requester clarified:"


class NotAwaitingAnswer(Exception):
    """The ticket has no open question: never asked, already answered,
    past `clarification.wait_minutes`, or handed to support."""


class Clarifications:
    """Asks a requester the clarifying question and takes their answer."""

    @staticmethod
    def options(
        retrieved_chunks: list[dict[str, Any]], titles: dict[str, str], th: ClarificationThresholds
    ) -> list[dict[str, str]]:
        """Chooses the pages a question offers: the pages of Jev's top 5
        whose yes/no score is within `option_margin` of the best, in Jev's
        order, each with a title. A chunk Jev didn't score offers nothing."""

        scored = [c for c in retrieved_chunks if c.get("option_score") is not None]
        if not scored:
            return []
        best = max(float(c["option_score"]) for c in scored)
        options: list[dict[str, str]] = []
        for c in scored:
            slug = c["kb_slug"]
            # Rounded so a page exactly at the margin is offered.
            if round(best - float(c["option_score"]), 9) > th.option_margin or slug not in titles:
                continue
            if all(o["slug"] != slug for o in options):
                options.append({"slug": slug, "title": titles[slug]})
            if len(options) == th.max_options:
                break
        return options

    def ask(self, ticket: Ticket, ai_run: AiRun, trace_id: str) -> bool:
        """Asks the requester which offered page they mean, if at least two are offered."""

        chunks = ai_run.retrieved_chunks or []
        titles = dict(
            KbArticle.objects.filter(
                slug__in={c["kb_slug"] for c in chunks}, is_active=True
            ).values_list("slug", "title")
        )
        options = self.options(chunks, titles, settings.THRESHOLDS.clarification)
        if len(options) < 2:
            return False
        TicketClarification.objects.create(
            ticket=ticket,
            ai_run=ai_run,
            question=CLARIFY_QUESTION,
            options=options,
            ticket_body_masked=ticket.body_masked,
        )
        AuditLog.objects.record(
            "clarification_asked",
            actor_type="system",
            ticket_id=ticket.id,
            payload={"ticket_public_id": ticket.public_id, "options": len(options)},
            trace_id=trace_id,
        )
        return True

    def answer(
        self, ticket_id: uuid.UUID, requester_id: uuid.UUID, answer: str, trace_id: str | None
    ) -> Ticket:
        """Masks the requester's answer, appends it to the ticket and runs the
        pipeline again."""

        ticket = Ticket.objects.get(id=ticket_id)
        if ticket.open_clarification() is None:
            raise NotAwaitingAnswer(ticket.public_id)
        masked = async_to_sync(mask_reply)(
            answer, settings.THRESHOLDS.masking.ner_max_share, list(ticket.pii_map)
        )
        quarantine = build_quarantine_entries(masked.placeholder_map)

        with transaction.atomic():
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            clarification = ticket.open_clarification()
            if clarification is None:
                raise NotAwaitingAnswer(ticket.public_id)

            clarification.answer_masked = masked.text_masked
            clarification.answered_at = timezone.now()
            clarification.save(update_fields=["answer_masked", "answered_at"])
            PiiQuarantine.objects.store(ticket, quarantine)
            ticket.pii_map = {**ticket.pii_map, **{ph: str(e.ref) for ph, e in quarantine.items()}}
            ticket.pii_level = PIILevel(ticket.pii_level).worse(masked.pii_level).value
            ticket.body_masked = f"{ticket.body_masked}\n\n{CLARIFIED_LABEL} {masked.text_masked}"
            ticket.status = "new"
            ticket.held_decision = None
            ticket.save(
                update_fields=["pii_map", "pii_level", "body_masked", "status", "held_decision"]
            )
            AuditLog.objects.record(
                "clarification_answered",
                actor_type="human",
                actor_id=requester_id,
                ticket_id=ticket.id,
                payload={"ticket_public_id": ticket.public_id, "pii_level": ticket.pii_level},
                trace_id=trace_id,
            )

        from apps.tickets import tasks

        tasks.process_ticket.delay(str(ticket.id))
        return ticket


# --- the clarifications service ---

clarifications = Clarifications()
