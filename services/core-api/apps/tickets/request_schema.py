"""
Request bodies for the tickets endpoints.
"""

from __future__ import annotations

from typing import Literal

from datetime import UTC, datetime
from enum import StrEnum

from ninja import Schema
from pydantic import ConfigDict, Field, field_validator


class TicketIn(Schema):
    """Raw submission from the employee. Never persisted as-is.

    The submit endpoint's request body, bound and validated by Ninja, so a
    submission that breaks these limits is rejected with a 422 before
    masking runs."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=10_000)
    attachments: list[str] = Field(default_factory=list[str], max_length=5)


class RevealReason(StrEnum):
    """Why a person reveals a quarantined value (F5, BR-F5-03)."""

    VERIFY_IDENTITY = "verify_identity"
    CONTACT_REQUESTER = "contact_requester"
    SECURITY_INVESTIGATION = "security_investigation"
    LEGAL_REQUEST = "legal_request"


class RevealIn(Schema):
    """One placeholder to reveal, with the reason for looking."""

    model_config = ConfigDict(extra="forbid")

    placeholder: str = Field(max_length=40)
    reason_code: RevealReason
    reason: str = Field(default="", max_length=2000)


class AccessLogFilter(Schema):
    """Filters on the PII access log."""

    ticket: str | None = None
    actor: str | None = None
    since: datetime | None = Field(default=None, alias="from")
    until: datetime | None = Field(default=None, alias="to")
    reason_code: RevealReason | None = None

    @field_validator("since", "until")
    @classmethod
    def in_utc(cls, value: datetime | None) -> datetime | None:
        """A time given without a zone is UTC (BR-X-09)."""
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class CommentIn(Schema):
    """A public comment or internal note from staff (F3 UC-F3-06)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    body: str = Field(min_length=1, max_length=10_000)
    visibility: Literal["public", "internal"]
    # Also move the ticket to `waiting_on_requester` in the same action.
    move_to_waiting: bool = False
    expected_version: int | None = None
