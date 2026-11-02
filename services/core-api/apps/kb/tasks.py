"""Celery entry points for KB governance (F6); the work is in `utils/`."""

from __future__ import annotations

from celery import shared_task

from apps.kb.utils.drafts import kb_drafts
from apps.kb.utils.gaps import kb_gaps


@shared_task
def publish_draft(draft_id: str) -> int:
    """Ingests the page a published draft wrote; the page keeps its old chunks if this fails."""
    return kb_drafts.ingest(draft_id)


@shared_task
def gaps_build() -> str:
    """Beat task: the weekly KB-gap report."""
    return str(kb_gaps.build().id)
