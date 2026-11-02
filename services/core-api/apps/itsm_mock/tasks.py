"""Celery entry points for runbooks (F12); the work is in `utils/runbooks.py`."""

from __future__ import annotations

import uuid

from celery import shared_task

from apps.itsm_mock.utils.runbooks import runbooks


@shared_task
def execute(execution_id: str) -> None:
    """Runs a queued runbook execution once; a row past `queued` is never sent again."""
    runbooks.run(uuid.UUID(execution_id))


@shared_task
def sweep() -> int:
    """Beat task: running executions past their wait become `unknown` (BR-F12-06)."""
    return runbooks.sweep()
