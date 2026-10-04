"""
Request bodies for the chat endpoints.
"""

from __future__ import annotations

from ninja import Schema
from pydantic import ConfigDict, Field


class ChatAskIn(Schema):
    """One question typed into the requester's chat. It becomes a ticket, so
    it carries the same body limits as a form submission (`TicketIn.body`)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: str = Field(min_length=10, max_length=10_000)
