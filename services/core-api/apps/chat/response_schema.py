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
    # Decided, but the handoff waits for the requester to ask for a ticket.
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


class ChatTurnOut(Schema):
    public_id: str
    # Masked, as stored: the raw text never outlives the submit request.
    question_masked: str
    state: ChatState
    answer: ChatAnswerOut | None = None
    created_at: datetime
