"""
Weekly drift monitoring — spec §7.2. Runs automatically (see
CELERY_BEAT_SCHEDULE) and writes an audit_log entry for each alert so
degraded calibration shows up next to every other operational event, not
in a separate dashboard nobody checks.
"""

from __future__ import annotations

import statistics
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.audit.services import audit
from apps.review.models import ReviewDecision
from apps.tickets.models import AiRun


@shared_task
def weekly_drift_check() -> dict:
    now = timezone.now()
    this_week = AiRun.objects.filter(created_at__gte=now - timedelta(days=7), trust_score__isnull=False)
    last_week = AiRun.objects.filter(
        created_at__gte=now - timedelta(days=14), created_at__lt=now - timedelta(days=7), trust_score__isnull=False
    )

    this_scores = list(this_week.values_list("trust_score", flat=True))
    last_scores = list(last_week.values_list("trust_score", flat=True))

    alerts: list[dict] = []
    th = settings.THRESHOLDS.alerts

    if this_scores and last_scores:
        drift = abs(statistics.mean(map(float, this_scores)) - statistics.mean(map(float, last_scores)))
        if drift > th.trust_score_drift_max:
            alerts.append({"alert": "trust_score_drift", "value": drift, "threshold": th.trust_score_drift_max})

    if len(this_scores) >= 2:
        std = statistics.stdev(map(float, this_scores))
        if std < 0.08:
            alerts.append({"alert": "trust_score_collapsed", "std": std})

    this_decisions = ReviewDecision.objects.filter(decided_at__gte=now - timedelta(days=7))
    last_decisions = ReviewDecision.objects.filter(
        decided_at__gte=now - timedelta(days=14), decided_at__lt=now - timedelta(days=7)
    )
    this_total, last_total = this_decisions.count(), last_decisions.count()
    if this_total and last_total:
        this_override = this_decisions.exclude(action_taken="approve").count() / this_total
        last_override = last_decisions.exclude(action_taken="approve").count() / last_total
        if abs(this_override - last_override) > th.override_rate_delta_max:
            alerts.append(
                {
                    "alert": "override_rate_delta",
                    "this_week": this_override,
                    "last_week": last_override,
                    "threshold": th.override_rate_delta_max,
                }
            )

    audit(
        "weekly_drift_check",
        actor_type="system",
        payload={"alerts": alerts, "checked_at": now.isoformat()},
    )
    return {"alerts": alerts}
