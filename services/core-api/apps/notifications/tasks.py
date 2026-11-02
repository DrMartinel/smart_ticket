"""
Celery entry points for notifications. The work lives in
`utils/dispatcher.py`.
"""

from __future__ import annotations

import uuid

from celery import shared_task

from apps.notifications.utils.dispatcher import dispatcher


@shared_task
def dispatch(message_id: str) -> str:
    return dispatcher.dispatch(uuid.UUID(message_id))


@shared_task
def sweep() -> dict[str, int]:
    """Beat task: re-queues stuck messages and dispatches due ones."""
    result = dispatcher.sweep()
    return {"requeued": result.requeued, "dispatched": result.dispatched}


@shared_task
def purge() -> int:
    """Beat task: deletes in-app messages past retention."""
    return dispatcher.purge()
