"""Ticket contracts — spec §4.2. ai-engine only ever sees the masked ticket."""

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.contracts.enums import PIILevel


class TicketMasked(BaseModel):
    """The only thing allowed to flow into the AI engine.

    `frozen=True` is deliberate: once masked, nothing downstream may edit the
    content. `placeholder_keys` carries keys only ("[EMAIL_1]"), never
    values — recovering a real value requires the quarantine endpoint and
    is logged (`pii_access_log`).
    """

    model_config = ConfigDict(frozen=True)

    ticket_public_id: str
    subject_masked: str
    body_masked: str
    pii_level: PIILevel
    placeholder_keys: list[str] = Field(default_factory=list)
