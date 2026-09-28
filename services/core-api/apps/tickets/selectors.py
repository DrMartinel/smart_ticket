"""Ticket pipeline reads."""

from __future__ import annotations

from django.utils import timezone

from apps.tickets.models import AiRun


def ai_cost_today_usd() -> float:
    """Total AI spend since 00:00 UTC — what `budget.daily_cost_ceiling_usd`
    is compared against."""
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = AiRun.objects.filter(created_at__gte=today_start).values_list("cost_usd", flat=True)
    return float(sum(c or 0 for c in total))
