"""
Request and response shapes for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

from typing import Any

from ninja import Schema

from apps.kb.models import KbArticle


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


def serialize_article(a: KbArticle) -> dict[str, Any]:
    return {
        "id": a.id,
        "slug": a.slug,
        "title": a.title,
        "category": a.category,
        "auto_reply_allowed": a.auto_reply_allowed,
        "risk_tier": a.risk_tier,
        "approved_by": a.approved_by_id,
        "is_active": a.is_active,
        "version": a.version,
    }
