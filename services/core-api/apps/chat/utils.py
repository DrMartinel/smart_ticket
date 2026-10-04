"""
What a requester sees of a chat ticket. A read over the ticket, its latest
routing decision, its AI run and the KB page the answer quotes, so it
belongs to no single model. Decides nothing: the state is read off what the
pipeline already did.
"""

from __future__ import annotations

from apps.chat.response_schema import ChatAnswerOut, ChatState, ChatTurnOut
from apps.kb.models import KbArticle
from apps.tickets.models import Ticket
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
    return ChatTurnOut(
        public_id=ticket.public_id,
        question_masked=ticket.body_masked,
        state=_state(ticket),
        answer=_answer(ticket) if ticket.status == "auto_replied" else None,
        created_at=ticket.created_at,
    )


def _state(ticket: Ticket) -> ChatState:
    if ticket.status == "new":
        return ChatState.THINKING
    if ticket.status == "auto_replied":
        return ChatState.ANSWERED
    if ticket.status == "awaiting_requester":
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
