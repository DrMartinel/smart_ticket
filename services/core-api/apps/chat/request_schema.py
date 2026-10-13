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


class ChatClarifyIn(Schema):
    """The requester's answer to the clarifying question (ADR-0023): a tapped
    option's title or what they typed."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    answer: str = Field(min_length=1, max_length=2_000)
