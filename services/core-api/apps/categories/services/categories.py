"""Changes to ticket categories, each audited with a reason (ADR-0049)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import F

from apps.accounts.domain.access import Access
from apps.accounts.domain.catalog import Permission
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.categories.domain.vocabulary import CategoryError, CategoryRefusal
from apps.categories.models import Category

_DISPLAY = ("name", "sort_order")
# What Jev is told a category means, and whether the router may route into it (ADR-0049).
_DEFINITION = ("description", "is_routable")


class CategoryConfig:
    """Edits a category's display fields, and for a manager its description and `is_routable`."""

    def edit(self, actor: User, slug: str, data: dict[str, Any]) -> Category:
        """Applies the given fields, bumps the version and audits the change."""
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise CategoryError(
                422, CategoryRefusal.REASON_REQUIRED, "say why the category changes"
            )
        with transaction.atomic():
            category = Category.objects.select_for_update().filter(slug=slug).first()
            if category is None:
                raise CategoryError(
                    404, CategoryRefusal.CATEGORY_NOT_FOUND, f"no category {slug!r}"
                )
            before = self.snapshot(category)
            changed = {
                name: data[name]
                for name in (*_DISPLAY, *_DEFINITION)
                if data.get(name) is not None and data[name] != getattr(category, name)
            }
            if not changed:
                return category
            if set(changed) & set(_DEFINITION) and not Access.of(actor).holds(
                Permission.CATEGORIES_DEFINE
            ):
                raise CategoryError(
                    403,
                    CategoryRefusal.NOT_ALLOWED,
                    "only a manager changes a category's description or routing",
                )
            for name, value in changed.items():
                setattr(category, name, value)
            category.version = F("version") + 1
            category.save(update_fields=[*changed, "version", "updated_at"])
            category.refresh_from_db()
            AuditLog.objects.record(
                "category_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "category": category.slug,
                    "reason": reason,
                    "before": before,
                    "after": self.snapshot(category),
                },
            )
        return category

    def snapshot(self, category: Category) -> dict[str, Any]:
        return {name: getattr(category, name) for name in (*_DISPLAY, *_DEFINITION, "version")}


category_config = CategoryConfig()
