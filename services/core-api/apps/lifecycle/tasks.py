"""
Celery entry points for the ticket lifecycle. The work lives in
`utils/engine.py`.
"""

from __future__ import annotations

import uuid

from celery import shared_task

from apps.lifecycle.utils.engine import lifecycle
from apps.lifecycle.utils.vocabulary import Phase


@shared_task
def run_phase(transfer_id: str, phase: str) -> None:
    lifecycle.run_phase(uuid.UUID(transfer_id), Phase(phase))


@shared_task
def run_event_actions(run_ids: list[str]) -> None:
    lifecycle.run_events(run_ids)


@shared_task
def watchdog() -> dict[str, int]:
    """Beat task: fails stalled runs, re-queues lost work, unlocks tickets."""
    return lifecycle.sweep()
