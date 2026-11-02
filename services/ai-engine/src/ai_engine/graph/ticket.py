"""
The ticket as it enters the graph: masked text only, and its PII level.
`TicketCategory` is here too: the categories Jev chooses among (ADR-0017).
Part of `AIRunRequest`'s body (schemas.py).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PIILevel(StrEnum):
    ROUTINE = "routine"  # proceeds
    SENSITIVE = "sensitive"  # proceeds, flagged
    CRITICAL = "critical"  # BLOCK
    MASK_FAILED = "mask_failed"  # HITL


class TicketCategory(StrEnum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    ACCESS = "access"
    SECURITY = "security"
    OTHER = "other"


# What happened to an earlier turn, in the words the prompts use.
_OUTCOME_WORDS = {
    "answered": "answered",
    "with_support": "handed to support",
    "clarify": "asked which page they meant",
    "suggest_ticket": "offered a ticket",
}


class PriorTurn(BaseModel):
    """An earlier turn of the same chat conversation, masked as stored (ADR-0034)."""

    model_config = ConfigDict(frozen=True)

    question_masked: str
    outcome: Literal["answered", "with_support", "clarify", "suggest_ticket"]
    answer_excerpt: str = ""


class TicketMasked(BaseModel):
    """The only ticket data that enters ai-engine. Frozen: masked content is
    never edited downstream. `placeholder_keys` are keys only, never values."""

    model_config = ConfigDict(frozen=True)

    ticket_public_id: str
    subject_masked: str
    body_masked: str
    pii_level: PIILevel
    placeholder_keys: list[str] = Field(default_factory=list)
    # Context for the draft and the proposal only: never a signal, never scored (ADR-0034).
    prior_turns: list[PriorTurn] = Field(default_factory=list)

    def earlier_turns(self) -> str:
        """The prior turns as the prompts show them, oldest first; empty without any."""
        lines = []
        for number, turn in enumerate(self.prior_turns, start=1):
            lines.append(f"Turn {number} ({_OUTCOME_WORDS[turn.outcome]}): {turn.question_masked}")
            if turn.answer_excerpt:
                lines.append(f"Answer given: {turn.answer_excerpt}")
        return "\n".join(lines)
