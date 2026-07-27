"""Few-shot pool governance — spec §3.5, thresholds from config/thresholds.yaml."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.fewshot.models import FewshotExample
from apps.tickets.models import Ticket


class FewshotError(Exception):
    pass


@transaction.atomic
def add_example(
    *, ticket: Ticket, category: str, input_text: str, output_json: dict, approver, user_confirmed: bool
) -> FewshotExample:
    if not user_confirmed:
        raise FewshotError("cannot add a few-shot example without user_confirmed=True")

    th = settings.THRESHOLDS.fewshot
    now = timezone.now()
    from apps.tickets.services.embeddings import embed_text

    return FewshotExample.objects.create(
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


def retract_for_reopened_ticket(ticket: Ticket, reason: str = "source ticket reopened") -> int:
    """Called when a ticket's `reopened_count` increments — a resolved
    ticket coming back means whatever example it produced is suspect."""
    return FewshotExample.objects.filter(source_ticket=ticket, retracted_at__isnull=True).update(
        retracted_at=timezone.now(), retract_reason=reason
    )


def active_examples_for_category(category: str, limit: int | None = None):
    th = settings.THRESHOLDS.fewshot
    qs = FewshotExample.objects.filter(
        category=category, retracted_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-approved_at")
    return qs[: limit or th.max_per_category]
