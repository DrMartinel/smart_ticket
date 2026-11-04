"""
The runbook catalog and runbook executions (F12, ADR-0038). A runbook never executes without a
human-approved `review_decisions` row backing it (ADR-0006), checked again at execute and at run.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from django.conf import settings
from django.db import models
from django.utils.crypto import salted_hmac

from apps.core.models import BaseModel
from apps.review.models import ReviewItem
from apps.tickets.models import Ticket


class ExecutorKind(StrEnum):
    KEYCLOAK = "keycloak"
    N8N = "n8n"
    MOCK = "mock"


class TargetRule(StrEnum):
    REPORTER = "reporter"
    ANY = "any"


class RunbookRisk(StrEnum):
    LOW = "low"
    HIGH = "high"


class ExecutionState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


# The states a new attempt on the same review item may follow.
RETRYABLE_STATES = frozenset({ExecutionState.FAILED})

# The fields a catalog change may set.
CATALOG_FIELDS = (
    "title",
    "executor",
    "config",
    "required_fields",
    "target_rule",
    "risk",
    "is_active",
)


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class Runbook(BaseModel):
    """One catalog entry; it runs only once a manager has approved its current fields."""

    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=200)
    executor = models.CharField(max_length=10, choices=_choices(ExecutorKind))
    config = models.JSONField(default=dict)
    required_fields = models.JSONField(default=list)
    target_rule = models.CharField(max_length=10, choices=_choices(TargetRule))
    risk = models.CharField(max_length=10, choices=_choices(RunbookRisk))
    is_active = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # A drafted change waiting for a manager; the fields above stay live until then.
    pending_change = models.JSONField(null=True, blank=True)
    drafted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    drafted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "itsm_runbooks"
        ordering = ["code"]

    def is_runnable(self) -> bool:
        return self.is_active and self.approved_at is not None


class RunbookExecutionQuerySet(models.QuerySet["RunbookExecution"]):
    def blocking_a_new_attempt(self, review_item: ReviewItem) -> RunbookExecutionQuerySet:
        """The item's executions that rule out another attempt: any not failed."""
        return self.filter(review_item=review_item).exclude(
            state__in=[s.value for s in RETRYABLE_STATES]
        )

    def past_their_wait(self, now: datetime) -> RunbookExecutionQuerySet:
        """Running executions whose callback or worker should have answered by `now`."""
        return self.filter(state=ExecutionState.RUNNING.value, awaiting_until__lt=now)


class RunbookExecution(BaseModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="runbook_executions")
    review_item = models.ForeignKey(
        ReviewItem, on_delete=models.PROTECT, related_name="runbook_executions"
    )
    runbook = models.ForeignKey(
        Runbook,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="executions",
        db_column="itsm_runbook_id",
    )
    # The runbook's code, in the pre-F12 `runbook_id` column.
    runbook_code = models.CharField(max_length=64, db_column="runbook_id")
    # The proposal's draft payload, and the payload the approver submitted, which is what runs.
    payload = models.JSONField()
    executed_payload = models.JSONField(default=dict)
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    second_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    second_approved_at = models.DateTimeField(null=True, blank=True)
    executor = models.CharField(max_length=10, blank=True, default="")
    state = models.CharField(
        max_length=30, choices=_choices(ExecutionState), default=ExecutionState.QUEUED.value
    )
    attempt = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    external_ref = models.CharField(max_length=500, blank=True, default="")
    error = models.TextField(blank=True, default="")
    result = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    awaiting_until = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")
    # Superseded by `state` (F12); no longer written. TODO: drop.
    status = models.CharField(max_length=20, null=True, blank=True, default=None)
    executed_at = models.DateTimeField(auto_now_add=True)

    objects = RunbookExecutionQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "runbook_executions"
        ordering = ["-executed_at"]

    def callback_token(self) -> str:
        """The secret n8n returns to finish this execution's run."""
        started = self.started_at.isoformat() if self.started_at else ""
        return salted_hmac("itsm.callback", f"{self.id}:{started}").hexdigest()
