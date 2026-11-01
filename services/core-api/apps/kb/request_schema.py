"""
Request bodies for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from django.db.models import Q
from ninja import FilterSchema, Schema
from pydantic import Field, field_validator

from apps.kb.models import DraftKind, DraftState
from apps.tickets.utils.router import RiskTier
from infrastructure.dtos import TicketCategory


class ArticleIn(Schema):
    slug: str
    title: str
    body: str
    category: str
    risk_tier: str = "high"


class ArticleFilter(FilterSchema):
    """Query parameters for `GET /api/kb`. The demo KB has thousands of
    articles, so the list is searched and paginated, never sent whole."""

    q: str | None = None
    category: str | None = None
    auto_reply_allowed: bool | None = None

    def filter_q(self, value: str | None) -> Q:
        return Q(slug__icontains=value) | Q(title__icontains=value) if value else Q()


class AutoReplyFlagIn(Schema):
    allowed: bool
    reason: str


class RiskTierIn(Schema):
    risk_tier: str
    reason: str


class DraftIn(Schema):
    """A new draft (F6 §h); `title` and `body` default to the live page's for an edit or retire."""

    kind: DraftKind = DraftKind.CREATE
    slug: str = Field(min_length=1, max_length=128)
    title: str = ""
    body: str = ""
    category: TicketCategory | None = None
    proposed_risk_tier: RiskTier | None = None
    change_note: str = ""
    gap_cluster_id: uuid.UUID | None = None


class DraftPatchIn(Schema):
    title: str | None = None
    body: str | None = None
    category: TicketCategory | None = None
    proposed_risk_tier: RiskTier | None = None
    change_note: str | None = None


class DraftFilter(Schema):
    state: DraftState | None = None
    author: str | None = None


class DraftReviewIn(Schema):
    decision: Literal["approve", "request_changes"]
    comment: str = ""


class BulkAllowedIn(Schema):
    slugs: list[str] = Field(min_length=1)
    allowed: bool
    reason: str


class AuthorityLogFilter(Schema):
    slug: str | None = None
    actor: str | None = None
    field: str | None = None
    since: datetime | None = Field(default=None, alias="from")
    until: datetime | None = Field(default=None, alias="to")

    @field_validator("since", "until")
    @classmethod
    def in_utc(cls, value: datetime | None) -> datetime | None:
        """A time given without a zone is UTC (BR-X-09)."""
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class GapDismissIn(Schema):
    reason: str
