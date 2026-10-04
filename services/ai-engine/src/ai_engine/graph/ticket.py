"""
The ticket as it enters the graph: masked text only, and its PII level.
`TicketCategory` is here too: the categories Jev chooses among (ADR-0017).
Part of `AIRunRequest`'s body (schemas.py).
"""

from __future__ import annotations

from enum import StrEnum

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


class TicketMasked(BaseModel):
    """The only ticket data that enters ai-engine. Frozen: masked content is
    never edited downstream. `placeholder_keys` are keys only, never values."""

    model_config = ConfigDict(frozen=True)

    ticket_public_id: str
    subject_masked: str
    body_masked: str
    pii_level: PIILevel
    placeholder_keys: list[str] = Field(default_factory=list)
