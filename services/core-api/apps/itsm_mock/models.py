"""
Mock ITSM API — stands in for a real ITSM/IAM/infra system. Its only job
that matters for the architecture is enforcing ADR-0006: a runbook never
executes without a human-approved `review_decisions` row backing it, even
if a caller somehow bypassed the router.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models

from apps.accounts.models import User
from apps.review.models import ReviewItem
from apps.tickets.models import Ticket


class RunbookExecution(models.Model):
    id: int
    ticket_id: int
    review_item_id: int
    executed_by_id: int

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="runbook_executions")
    review_item = models.ForeignKey(
        ReviewItem, on_delete=models.PROTECT, related_name="runbook_executions"
    )
    runbook_id = models.CharField(max_length=64)
    payload: models.JSONField[dict[str, Any]] = models.JSONField()
    executed_by = models.ForeignKey[User](settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    result: models.JSONField[dict[str, Any]] = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="succeeded")
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "runbook_executions"
