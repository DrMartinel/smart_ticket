"""Few-shot pool reads — spec §3.5. TTL and retraction are enforced here, at
query time, so an expired or retracted example is out of the pool the moment
it qualifies, whether or not the hourly expiry task has run yet."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.fewshot.models import FewshotExample


def active_examples_for_category(category: str, limit: int | None = None):
    th = settings.THRESHOLDS.fewshot
    qs = FewshotExample.objects.filter(
        category=category, retracted_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-approved_at")
    return qs[: limit or th.max_per_category]
