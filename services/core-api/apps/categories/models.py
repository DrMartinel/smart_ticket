"""Ticket categories: the set a ticket's category comes from, and what each one means (ADR-0049)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from django.db.models import QuerySet

from apps.categories.domain.vocabulary import CategoryError, CategoryRefusal
from apps.core.models import BaseModel

if TYPE_CHECKING:
    from apps.lifecycle.models import Workflow


class CategoryQuerySet(QuerySet["Category"]):
    def active(self) -> CategoryQuerySet:
        """The categories a ticket may be given now, in display order."""
        return self.filter(is_active=True).order_by("sort_order", "slug")

    def for_triage(self) -> CategoryQuerySet:
        """The active categories in slug order, as Jev is offered them (ADR-0049)."""
        return self.active().order_by("slug")

    def is_security(self, slug: str | None) -> bool:
        """Whether `slug` names a security category, active or not."""
        return slug is not None and self.filter(slug=slug, is_security=True).exists()

    def workflow_of(self, slug: str | None) -> Workflow | None:
        """The workflow tickets in category `slug` move into at handoff, if it names one."""
        if slug is None:
            return None
        found = self.select_related("workflow").filter(slug=slug).first()
        return found.workflow if found is not None else None

    def require(self, slug: str) -> Category:
        """The active category `slug`; refuses one that is unknown or inactive."""
        category = self.active().filter(slug=slug).first()
        if category is None:
            raise CategoryError(
                422, CategoryRefusal.UNKNOWN_CATEGORY, f"no active category {slug!r}"
            )
        return category


class Category(BaseModel):
    """One ticket category. The slug is what every `category` column stores."""

    slug = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    is_security = models.BooleanField(default=False)
    is_routable = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    # The workflow its tickets move into at handoff; none keeps them in the default (ADR-0049).
    workflow = models.ForeignKey(
        "lifecycle.Workflow",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="categories",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CategoryQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "ticket_categories"
        ordering = ["sort_order", "slug"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(description__regex=r"^\s*$"),
                name="ck_ticket_categories_description_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return self.slug
