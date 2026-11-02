"""Celery entry points for mass incidents (F7); the work is in `utils/incidents.py`."""

from __future__ import annotations

from celery import shared_task

from apps.incidents.utils.incidents import incidents


@shared_task
def sweep() -> dict[str, int]:
    """Beat task: target-breach notices and closing resolved incidents (BR-F7-10)."""
    return incidents.sweep()
