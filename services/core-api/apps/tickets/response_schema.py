"""
Response shapes for the ticket endpoints.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema


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
