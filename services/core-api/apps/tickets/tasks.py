"""
Celery entry points for tickets. Each task stays here because Celery names
it after this module's path — `apps.tickets.tasks.<name>` is what the beat
schedule and any message already in the broker refer to. The work itself
lives in `utils/pipeline.py` and on the models.

`acks_late=True` (settings) + an idempotency key of `{ticket_id}:{attempt}`
on `AiRun` mean a worker dying mid-task and Celery redelivering the
message results in, at worst, a second AiRun row for the same attempt
number being rejected by the unique constraint — not a double auto-reply
sent to the user (spec §10.3). The key and the collision handling are in
`utils/pipeline.py`.
"""

from __future__ import annotations

import uuid

from celery import Task, shared_task
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.tickets.models import PiiQuarantine
from apps.tickets.utils.pipeline import TaskResult, ticket_process


@shared_task(bind=True, max_retries=0)
def process_ticket(self: Task[[str], TaskResult], ticket_id: str) -> TaskResult:
    return ticket_process(ticket_id)


@shared_task
def reopen_ticket(ticket_id: str) -> None:
    """Reopens a completed ticket; the requester's reopen endpoint runs the same service (F3)."""
    from apps.requester.utils.tickets import requester_tickets

    requester_tickets.reopen_now(uuid.UUID(ticket_id), None)


@shared_task
def expire_pii_quarantine() -> int:
    """Beat task (hourly). Hard TTL enforcement for raw PII — spec §3.1:
    `expires_at TIMESTAMPTZ NOT NULL -- now() + 72h`."""
    expired = PiiQuarantine.objects.filter(expires_at__lte=timezone.now())
    count = expired.count()
    expired.delete()
    if count:
        AuditLog.objects.record(
            "pii_quarantine_expired", actor_type="system", payload={"count": count}
        )
    return count
