"""Celery entry points for the requester's side (F3); the work is in `utils/tickets.py`."""

from __future__ import annotations

from celery import shared_task

from apps.requester.utils.tickets import requester_tickets


@shared_task
def sweep() -> dict[str, int]:
    """Beat task: ends idle conversations and resolves stale waits on the requester (BR-F3-11)."""
    return requester_tickets.sweep()
