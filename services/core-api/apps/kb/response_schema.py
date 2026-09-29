"""
Response shapes for the KB endpoints (spec §3.2).
"""

from __future__ import annotations

import uuid

from ninja import Field, Schema


class ArticleOut(Schema):
    id: uuid.UUID
    slug: str
    title: str
    category: str
    source_url: str
    auto_reply_allowed: bool
    risk_tier: str
    approved_by: uuid.UUID | None = Field(alias="approved_by_id")
    is_active: bool
    version: int


class ReingestOut(Schema):
    slug: str
    chunks: int
