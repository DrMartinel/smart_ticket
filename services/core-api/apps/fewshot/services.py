"""Few-shot pool governance — spec §3.5, thresholds from config/thresholds.yaml."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.fewshot.models import FewshotExample
from apps.tickets.models import Ticket
from infrastructure.embeddings import embed_text


class FewshotError(Exception):
    pass


@transaction.atomic
def add_example(
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
