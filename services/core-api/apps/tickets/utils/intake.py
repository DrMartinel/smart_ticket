"""Opens tickets: a person's submission, masked inline (spec §5), and the ticket an agent turn
hands to a person (F15)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.tickets.models import PiiQuarantine, Ticket, TicketSource
from apps.tickets.request_schema import TicketIn
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.utils.masking import mask

if TYPE_CHECKING:
    from apps.agent.models import AgentTurn
    from apps.chat.models import Conversation
    from infrastructure.dtos import AgentHandoffReason


@dataclass(frozen=True)
class MaskedTicket:
    """What a new ticket holds, already masked."""

    reporter: User
    subject_masked: str
    body_masked: str
    pii_level: str
    source: TicketSource
    conversation: Conversation | None = None
    reopened_from: Ticket | None = None
    agent_turn: AgentTurn | None = None
    agent_handoff_reason: str | None = None


class TicketIntake:
    """Masks, stores and queues new tickets."""

    def submit(
        self,
        *,
        reporter: User,
        ticket_in: TicketIn,
        trace_id: str | None,
        source: TicketSource = TicketSource.FORM,
        conversation: Conversation | None = None,
        reopened_from: Ticket | None = None,
        agent_turn: AgentTurn | None = None,
    ) -> Ticket:
        """Masks `ticket_in` inline, stores it with its quarantine entries and queues its
        pipeline run. A masking failure stores the ticket at `mask_failed`; it never raises.
        A ticket an agent turn asks for also gets the conversation's entries its text names."""
        result = async_to_sync(mask)(ticket_in, settings.THRESHOLDS.masking.ner_max_share)
        entries = build_quarantine_entries(result.placeholder_map)

        def store(ticket: Ticket) -> dict[str, str]:
            PiiQuarantine.objects.store(ticket, entries)
            own = {ph: str(entry.ref) for ph, entry in entries.items()}
            if agent_turn is None:
                return own
            # Imported here: the agent app imports this module.
            from apps.agent.models import AgentTurn

            conversation_map = AgentTurn.objects.pii_map_of(agent_turn.conversation_id)
            inherited = {ph: ref for ph, ref in conversation_map.items() if ph not in own}
            text = f"{result.subject_masked}\n{result.body_masked}"
            return own | PiiQuarantine.objects.copy_to(ticket, inherited, text)

        ticket = self._open(
            MaskedTicket(
                reporter=reporter,
                subject_masked=result.subject_masked,
                body_masked=result.body_masked,
                pii_level=result.pii_level.value,
                source=source,
                conversation=conversation,
                reopened_from=reopened_from,
                agent_turn=agent_turn,
            ),
            store,
            trace_id=trace_id,
            audit={},
        )
        self.queue(ticket)
        return ticket

    def open_for_agent(
        self,
        turn: AgentTurn,
        reason: AgentHandoffReason,
        conversation: Conversation | None,
        audit: dict[str, str],
    ) -> Ticket:
        """Stores the chat ticket an agent turn hands to a person: the turn's masked message, the
        conversation's quarantine entries it names and the agent's reason (BR-F15-14, -18). Does
        not queue its pipeline run; the caller does, after its transaction commits."""
        from apps.agent.models import AgentTurn
        from apps.chat.utils.turns import subject_of

        conversation_map = AgentTurn.objects.pii_map_of(turn.conversation_id)
        return self._open(
            MaskedTicket(
                reporter=turn.conversation.user,
                subject_masked=subject_of(turn.message_masked),
                body_masked=turn.message_masked,
                pii_level=turn.pii_level,
                source=TicketSource.CHAT,
                conversation=conversation,
                agent_turn=turn,
                agent_handoff_reason=reason,
            ),
            lambda ticket: PiiQuarantine.objects.copy_to(
                ticket, conversation_map, turn.message_masked
            ),
            trace_id=None,
            audit=audit,
        )

    def queue(self, ticket: Ticket) -> None:
        """Queues the ticket's pipeline run; called once its row is committed."""
        # Imported here: tasks imports the pipeline, which imports the models.
        from apps.tickets import tasks

        tasks.process_ticket.delay(str(ticket.id))

    def _open(
        self,
        masked: MaskedTicket,
        store: Callable[[Ticket], dict[str, str]],
        *,
        trace_id: str | None,
        audit: dict[str, str],
    ) -> Ticket:
        """Creates the ticket, stores its quarantine entries, starts its workflow and audits it."""
        # Imported here: the lifecycle engine imports the models.
        from apps.lifecycle.utils.engine import lifecycle

        with transaction.atomic():
            ticket = Ticket.objects.create(
                public_id=Ticket.objects.next_public_id(),
                reporter=masked.reporter,
                requester_department_id=masked.reporter.department_id,
                subject_masked=masked.subject_masked,
                body_masked=masked.body_masked,
                pii_level=masked.pii_level,
                source=masked.source.value,
                conversation=masked.conversation,
                reopened_from=masked.reopened_from,
                agent_turn=masked.agent_turn,
                agent_handoff_reason=masked.agent_handoff_reason,
            )
            ticket.pii_map = store(ticket)
            ticket.save(update_fields=["pii_map"])
            lifecycle.start(ticket)
            AuditLog.objects.record(
                "ticket_submitted",
                actor_type="human",
                actor_id=masked.reporter.id,
                ticket_id=ticket.id,
                payload={
                    "ticket_public_id": ticket.public_id,
                    "pii_level": ticket.pii_level,
                    "source": ticket.source,
                    "trace_id": trace_id,
                    **audit,
                },
                trace_id=trace_id,
            )
        return ticket


ticket_intake = TicketIntake()
