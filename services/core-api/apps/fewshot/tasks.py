from celery import shared_task
from django.utils import timezone

from apps.fewshot.models import FewshotExample


@shared_task
def expire_fewshot_examples() -> int:
    """Beat task (hourly, see config/settings/base.py CELERY_BEAT_SCHEDULE).
    TTL expiry is a query-time filter already (see services.py), so this
    task only needs to retract rows for observability/cleanup purposes."""
    stale = FewshotExample.objects.filter(retracted_at__isnull=True, expires_at__lte=timezone.now())
    count = stale.update(retracted_at=timezone.now(), retract_reason="ttl_expired")
    return count
