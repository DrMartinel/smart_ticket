"""Response shapes of the category endpoints."""

from __future__ import annotations

from ninja import Schema


class CategoryOut(Schema):
    slug: str
    name: str
    description: str
    is_active: bool
    is_security: bool
    is_routable: bool
    sort_order: int
    version: int
