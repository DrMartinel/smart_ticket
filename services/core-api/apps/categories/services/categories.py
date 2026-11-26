"""Changes to ticket categories, each audited with a reason (ADR-0049)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import F

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.categories.domain.vocabulary import CategoryError, CategoryRefusal
from apps.categories.models import Category

_FIELDS = ("name", "sort_order")


class CategoryConfig:
    """Edits a category's display fields; its slug, description and flags stay as seeded."""

    def edit(self, actor: User, slug: str, data: dict[str, Any]) -> Category:
        """Applies the given `name` and `sort_order`, bumps the version and audits the change."""
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise CategoryError(
                422, CategoryRefusal.REASON_REQUIRED, "say why the category changes"
            )
        with transaction.atomic():
            category = self.locked(slug)
            before = self.snapshot(category)
            changed = {
                name: data[name]
                for name in _FIELDS
                if data.get(name) is not None and data[name] != getattr(category, name)
            }
            if not changed:
                return category
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

    def locked(self, slug: str) -> Category:
        category = Category.objects.select_for_update().filter(slug=slug).first()
        if category is None:
            raise CategoryError(404, CategoryRefusal.CATEGORY_NOT_FOUND, f"no category {slug!r}")
        return category

    def snapshot(self, category: Category) -> dict[str, Any]:
        return {name: getattr(category, name) for name in (*_FIELDS, "version")}


category_config = CategoryConfig()
