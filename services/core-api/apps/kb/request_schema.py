"""
Request bodies for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

from ninja import Schema


class ArticleIn(Schema):
    slug: str
    title: str
    body: str
    category: str
    risk_tier: str = "high"


class AutoReplyFlagIn(Schema):
    allowed: bool
    reason: str


class RiskTierIn(Schema):
    risk_tier: str
    reason: str
