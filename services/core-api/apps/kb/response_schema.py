"""
Response shapes for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

from ninja import Field, Schema


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
