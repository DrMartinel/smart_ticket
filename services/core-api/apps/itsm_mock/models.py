"""
Mock ITSM API — stands in for a real ITSM/IAM/infra system. Its only job
that matters for the architecture is enforcing ADR-0006: a runbook never
executes without a human-approved `review_decisions` row backing it, even
if a caller somehow bypassed the router.
"""

from __future__ import annotations


from typing import TypedDict

from django.conf import settings
from django.db import models, transaction

from apps.core.models import BaseModel
from apps.accounts.models import User
from apps.review.models import ReviewItem
from apps.tickets.models import Ticket


# A tiny fixed set of "runbooks" simulating real ITSM actions. This is a mock,
# so "execution" only records a plausible result; no real system is called.
class Runbook(TypedDict):
    title: str
    required_fields: list[str]


RUNBOOK_REGISTRY: dict[str, Runbook] = {
    "RB-RESET-PASSWORD": {
        "title": "Reset user password",
        "required_fields": ["target_username"],
    },
    "RB-GRANT-ACCESS": {
        "title": "Grant application access",
        "required_fields": ["target_username", "application", "access_level"],
    },
    "RB-RESTART-SERVICE": {
        "title": "Restart a service",
        "required_fields": ["service_name", "host"],
    },
}


class RunbookError(Exception):
    pass


class RunbookExecutionManager(models.Manager["RunbookExecution"]):
    @transaction.atomic
    def execute(self, *, review_item: ReviewItem, executed_by: User) -> RunbookExecution:
        """ADR-0006, enforced here as a second, independent check beyond the
        router: this refuses to run unless an actual approving decision exists
        on this review item, regardless of how the caller got here."""

        approving_decision = (
            review_item.decisions.filter(action_taken="approve").order_by("-decided_at").first()
        )
        if approving_decision is None:
            raise RunbookError(
                "no approving review_decisions row for this review item — "
                "runbooks NEVER execute without human approval (ADR-0006)"
            )
        if review_item.queue != "runbook_approval":
            raise RunbookError("review item is not a runbook_approval item")

        ai_run = review_item.ai_run
        draft = (ai_run.proposed_draft or {}) if ai_run else {}
        runbook_id = draft.get("runbook_id")
        payload = draft.get("draft_payload", {})

        if not isinstance(runbook_id, str) or runbook_id not in RUNBOOK_REGISTRY:
            raise RunbookError(f"unknown runbook_id: {runbook_id!r}")
        spec = RUNBOOK_REGISTRY[runbook_id]

        missing = [f for f in spec["required_fields"] if f not in payload]
        if missing:
            raise RunbookError(f"runbook {runbook_id} missing required fields: {missing}")

        result = {"simulated": True, "runbook": spec["title"], "applied_payload": payload}

        return self.create(
            ticket=review_item.ticket,
            review_item=review_item,
            runbook_id=runbook_id,
            payload=payload,
            executed_by=executed_by,
            result=result,
            status="succeeded",
        )


class RunbookExecution(BaseModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="runbook_executions")
    review_item = models.ForeignKey(
        ReviewItem, on_delete=models.PROTECT, related_name="runbook_executions"
    )
    runbook_id = models.CharField(max_length=64)
    payload = models.JSONField()
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="succeeded")
    executed_at = models.DateTimeField(auto_now_add=True)

    objects = RunbookExecutionManager()

    class Meta(BaseModel.Meta):
        db_table = "runbook_executions"
