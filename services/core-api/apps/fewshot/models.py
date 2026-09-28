"""Few-shot pool — spec §3.5. Governance rules enforced at both the DB
level (`chk_fewshot_confirmed`) and on `FewshotExampleManager` (TTL,
retraction)."""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone
from pgvector.django import VectorField

from infrastructure.ai_engine import TicketCategory
from apps.accounts.models import User
from apps.tickets.models import Ticket
from infrastructure.embeddings import embed_text


class FewshotError(Exception):
    pass


class FewshotExampleManager(models.Manager["FewshotExample"]):
    @transaction.atomic
    def add_confirmed(
        self,
        *,
        ticket: Ticket,
        category: str,
        input_text: str,
        output_json: dict[str, Any],
        approver: User,
        user_confirmed: bool,
    ) -> FewshotExample:
        if not user_confirmed:
            raise FewshotError("cannot add a few-shot example without user_confirmed=True")

        th = settings.THRESHOLDS.fewshot
        now = timezone.now()
        return self.create(
            source_ticket=ticket,
            category=category,
            input_text=input_text,
            output_json=output_json,
            embedding=embed_text(input_text),
            approver=approver,
            approved_at=now,
            user_confirmed=True,
            expires_at=now + timezone.timedelta(days=th.ttl_days),
        )

    def retract_for_ticket(self, ticket: Ticket, reason: str = "source ticket reopened") -> int:
        """Called when a ticket's `reopened_count` increments — a resolved
        ticket coming back means whatever example it produced is suspect."""
        return self.filter(source_ticket=ticket, retracted_at__isnull=True).update(
            retracted_at=timezone.now(), retract_reason=reason
        )

    def active_for_category(
        self, category: str, limit: int | None = None
    ) -> QuerySet[FewshotExample]:
        """The pool for one category (spec §3.5). TTL and retraction are
        enforced here, at query time, so an expired or retracted example is out
        of the pool the moment it qualifies, whether or not the hourly expiry
        task has run yet."""
        th = settings.THRESHOLDS.fewshot
        qs = self.filter(
            category=category, retracted_at__isnull=True, expires_at__gt=timezone.now()
        ).order_by("-approved_at")
        return qs[: limit or th.max_per_category]


class FewshotExample(models.Model):
    id: int
    source_ticket_id: int
    approver_id: int

    source_ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="fewshot_examples"
    )
    category = models.CharField(max_length=20, choices=[(c.value, c.value) for c in TicketCategory])
    input_text = models.TextField()  # already masked
    output_json: models.JSONField[dict[str, Any]] = models.JSONField()
    embedding = VectorField(dimensions=1024, null=True, blank=True)

    approver = models.ForeignKey[User](settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_at = models.DateTimeField()
    user_confirmed = models.BooleanField(default=False)  # required to enter the pool
    expires_at = models.DateTimeField()  # approved_at + ttl_days
    retracted_at = models.DateTimeField(null=True, blank=True)  # set when source ticket reopens
    retract_reason = models.TextField(null=True, blank=True)
    version = models.IntegerField(default=1)

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[FewshotExampleManager] = FewshotExampleManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    class Meta:
        db_table = "fewshot_examples"
        # chk_fewshot_confirmed CHECK constraint is added by
        # infra/migrations/sql/0003_constraints_and_triggers.sql.
