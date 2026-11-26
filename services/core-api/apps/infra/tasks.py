"""Celery entry points for a ticket's cues (F17 §o.11); the work is in `services/cues.py`."""

from __future__ import annotations

import uuid

from celery import shared_task
from django.conf import settings

from apps.infra.services.cues import cues


@shared_task(
    name="infra.ticket_cues", max_retries=0, soft_time_limit=settings.INFRA_CUE_SOFT_TIME_LIMIT_SEC
)
def ticket_cues(ticket_id: str, transfer_id: str) -> None:
    cues.collect(uuid.UUID(ticket_id), uuid.UUID(transfer_id))


@shared_task(
    name="infra.linked_cues", max_retries=0, soft_time_limit=settings.INFRA_CUE_SOFT_TIME_LIMIT_SEC
)
def linked_cues(run_id: str) -> None:
    cues.collect_linked(uuid.UUID(run_id))
