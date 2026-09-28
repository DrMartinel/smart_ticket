"""
Request shapes for the ticket endpoints.
"""

from __future__ import annotations

from ninja import Schema


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
