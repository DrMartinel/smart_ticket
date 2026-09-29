"""
Request bodies for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

from django.db.models import Q
from ninja import FilterSchema, Schema


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
