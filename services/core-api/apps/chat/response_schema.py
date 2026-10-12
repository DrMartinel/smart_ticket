"""
Response shapes for the chat endpoints: one question and where it stands,
as the requester is allowed to see it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from ninja import Schema


class ChatState(StrEnum):
    # Masked and handed to the pipeline; no decision yet.
    THINKING = "thinking"
    # The router chose auto-reply, live (not shadow), from an approved KB page.
    ANSWERED = "answered"
    # The router chose to ask which shown page the requester means, and the
    # question is open (ADR-0023). They can answer, or ask for a person.
    CLARIFY = "clarify"
    # Decided, but the handoff waits for the requester to ask for a ticket.
    # Also where an unanswered question ends once its wait is over.
    SUGGEST_TICKET = "suggest_ticket"
    # With support: the requester asked for a ticket, or the decision was one
    # that never waits (`pipeline.waits_for_requester`).
    WITH_SUPPORT = "with_support"


class ChatAnswerOut(Schema):
    text: str
    # Verbatim from the KB page; the quote checks matched it before the
    # router allowed the answer.
    quote: str
    kb_title: str
    kb_url: str


class ChatClarificationOut(Schema):
    # The LLM's question, checked by the router before it was asked.
    question: str
    # The KB pages' titles, which is what the requester taps; slugs are
    # never shown.
    options: list[str]
    # Masked, as stored. None until answered.
    answer_masked: str | None = None


class ChatTurnOut(Schema):
    public_id: str
    # Masked, as stored: the raw text never outlives the submit request.
    question_masked: str
    state: ChatState
    answer: ChatAnswerOut | None = None
    # The question asked of the requester, open or answered or expired.
    clarification: ChatClarificationOut | None = None
    created_at: datetime
