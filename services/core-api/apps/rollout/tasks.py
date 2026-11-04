"""Celery entry points for rollout control (F9); the work is in `utils/rollout.py`."""

from __future__ import annotations

from celery import shared_task

from apps.rollout.utils.rollout import rollout


@shared_task
def sweep() -> dict[str, int]:
    """Beat task: reports unmet gates of live branches."""
    return rollout.sweep()
