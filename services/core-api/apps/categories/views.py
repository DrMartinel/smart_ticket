"""Category endpoints: the list every console reads, and renaming or reordering one (ADR-0049)."""

from __future__ import annotations

from django.db.models import QuerySet
from ninja import Router

from apps.accounts.domain.catalog import Permission
from apps.accounts.permissions import AgentTier, AuthedRequest, SessionAuth, require
from apps.categories.models import Category
from apps.categories.request_schema import CategoryPatch
from apps.categories.response_schema import CategoryOut
from apps.categories.services.categories import category_config

router = Router(tags=["categories"])


@router.get("", auth=SessionAuth(), response=list[CategoryOut])
@require(Permission.CATEGORIES_READ, agent=AgentTier.NONE)
def categories(request: AuthedRequest) -> QuerySet[Category]:
    return Category.objects.all()


@router.patch("/{slug}", auth=SessionAuth(), response=CategoryOut)
@require(Permission.CATEGORIES_MANAGE, agent=AgentTier.NONE)
def update_category(request: AuthedRequest, slug: str, payload: CategoryPatch) -> Category:
    return category_config.edit(request.auth.user, slug, payload.model_dump(mode="json"))
