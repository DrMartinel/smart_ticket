"""
Request bodies for the tickets endpoints.
"""

from __future__ import annotations

from ninja import Schema
from pydantic import ConfigDict, Field


class TicketIn(Schema):
    """Raw submission from the employee. Never persisted as-is.

    The submit endpoint's request body, bound and validated by Ninja, so a
    submission that breaks these limits is rejected with a 422 before
    masking runs."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=10_000)
    attachments: list[str] = Field(default_factory=list[str], max_length=5)
