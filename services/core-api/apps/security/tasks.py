"""Celery entry points for the security inbox (F8); the work is in `utils/alerts.py`."""

from __future__ import annotations

from celery import shared_task

from apps.security.utils.alerts import security_alerts


@shared_task
def sweep() -> dict[str, int]:
    """Beat task: overdue-acknowledgement notices and refusal bursts (BR-F8-04, BR-F8-08)."""
    return security_alerts.sweep()
