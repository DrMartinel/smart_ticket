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

from celery import Task, shared_task
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.fewshot.models import FewshotExample
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.utils.pipeline import TaskResult, ticket_process


@shared_task(bind=True, max_retries=0)
def process_ticket(self: Task[[int], TaskResult], ticket_id: int) -> TaskResult:
    return ticket_process(ticket_id)


@shared_task
def reopen_ticket(ticket_id: int) -> None:
    """Called by whatever surface lets a reporter reopen a resolved ticket
    (not built out as its own endpoint in this build, but wired here so
    the few-shot retraction rule — spec §3.5 — has a concrete trigger)."""
    ticket = Ticket.objects.get(id=ticket_id)
    ticket.reopened_count += 1
    ticket.status = "reopened"
    ticket.save(update_fields=["reopened_count", "status"])
    FewshotExample.objects.retract_for_ticket(ticket)
    AuditLog.objects.record(
        "ticket_reopened",
        actor_type="human",
        ticket_id=ticket.id,
        payload={"reopened_count": ticket.reopened_count},
    )


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
