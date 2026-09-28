"""Ticket contracts — spec §4.2."""

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import PIILevel


class TicketIn(BaseModel):
    """Raw submission from the employee. Never persisted as-is."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=10_000)
    attachments: list[str] = Field(default_factory=list, max_length=5)


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
