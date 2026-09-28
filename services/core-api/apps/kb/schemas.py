"""
Request and response shapes for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

from ninja import Field, Schema


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


class ArticleOut(Schema):
    id: int
    slug: str
    title: str
    category: str
    auto_reply_allowed: bool
    risk_tier: str
    approved_by: int | None = Field(alias="approved_by_id")
    is_active: bool
    version: int


class ReingestOut(Schema):
    slug: str
    chunks: int
