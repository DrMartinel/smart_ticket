"""
What a requester sees of a chat ticket. A read over the ticket, its latest
routing decision, its AI run and the KB page the answer quotes, so it
belongs to no single model. Decides nothing: the state is read off what the
pipeline already did.
"""

from __future__ import annotations

from apps.chat.response_schema import (
    ChatAnswerOut,
    ChatClarificationOut,
    ChatState,
    ChatTurnOut,
)
from apps.kb.models import KbArticle
from apps.tickets.models import Ticket, TicketClarification
from apps.tickets.request_schema import TicketIn
from infrastructure.dtos import AutoReplyProposal

# How much of the question becomes the ticket's subject: a reviewer's
# one-line summary, not a limit on what is asked (the body keeps it all).
_SUBJECT_CHARS = 120


def ticket_in_from_message(message: str) -> TicketIn:
    words = " ".join(message.split())
    subject = words if len(words) <= _SUBJECT_CHARS else words[: _SUBJECT_CHARS - 1] + "…"
    return TicketIn(subject=subject, body=message)


def chat_turn(ticket: Ticket) -> ChatTurnOut:
    asked = ticket.latest_clarification()
    return ChatTurnOut(
        public_id=ticket.public_id,
        # What the requester typed, before any answer was appended.
        question_masked=asked.ticket_body_masked if asked else ticket.body_masked,
        state=chat_state(ticket, asked),
        answer=_answer(ticket) if ticket.status == "auto_replied" else None,
        clarification=ChatClarificationOut.from_row(asked) if asked else None,
        created_at=ticket.created_at,
        status_name=_support_status_name(ticket),
        resolved=ticket.resolved_at is not None,
        conversation_id=ticket.conversation_id,
    )


def _support_status_name(ticket: Ticket) -> str | None:
    """The status a person moved the ticket into; none for the pipeline's own statuses."""
    status = ticket.workflow_status
    return status.name if status is not None and not status.is_pipeline else None


def chat_state(ticket: Ticket, asked: TicketClarification | None) -> ChatState:
    """Where a chat question stands, as the requester sees it."""
    if ticket.status == "new":
        return ChatState.THINKING
    if ticket.status == "auto_replied":
        return ChatState.ANSWERED
    if ticket.status == "awaiting_requester":
        if asked is not None and ticket.awaits_answer_to(asked):
            return ChatState.CLARIFY
        return ChatState.SUGGEST_TICKET
    return ChatState.WITH_SUPPORT


def _answer(ticket: Ticket) -> ChatAnswerOut | None:
    """The auto-reply the router allowed: the proposal of the run its
    decision was made on, and the KB page that proposal names. The page is
    read again here for its title and link only, never for authority."""
    decision = ticket.routing_decisions.select_related("ai_run").order_by("-decided_at").first()
    if decision is None or decision.ai_run is None or decision.ai_run.proposed_draft is None:
        return None
    proposal = AutoReplyProposal.model_validate(decision.ai_run.proposed_draft)
    kb = KbArticle.objects.filter(slug=proposal.kb_slug).first()
    return ChatAnswerOut(
        text=proposal.answer_draft,
        quote=proposal.verbatim_quote,
        kb_title=kb.title if kb else proposal.kb_slug,
        kb_url=kb.source_url if kb else "",
    )
