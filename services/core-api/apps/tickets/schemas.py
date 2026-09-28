"""
Request and response shapes for the ticket endpoints.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema


class TicketSubmitIn(Schema):
    """Django Ninja's own input schema for body binding — a plain `dict`
    parameter doesn't bind the JSON request body the way a Schema/pydantic
    model does. `contracts.ticket.TicketIn` (the real domain contract,
    with its length constraints) is still what actually validates the
    submission, in `api.submit_ticket`; this class only exists to get the
    raw JSON off the wire correctly."""

    subject: str
    body: str
    attachments: list[str] = []


class TicketSubmitOut(Schema):
    ticket_public_id: str = Field(alias="public_id")
    status: str
    pii_level: str


class TicketOut(Schema):
    public_id: str
    subject_masked: str
    body_masked: str
    pii_level: str
    status: str
    category: str | None
    created_at: datetime
