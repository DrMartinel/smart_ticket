"""Per-branch rollout flags, their requests and gates, and reviewed threshold change requests
(F9, ADR-0035)."""

from __future__ import annotations

from enum import StrEnum

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.rollout.utils.vocabulary import (
    ChangeState,
    Comparator,
    FlagBranch,
    FlagState,
    GateMetric,
    RequestState,
)


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    return [(m.value, m.value) for m in enum]


class RolloutFlag(BaseModel):
    branch = models.CharField(max_length=30, choices=_choices(FlagBranch), unique=True)
    state = models.CharField(
        max_length=12, choices=_choices(FlagState), default=FlagState.OFF.value
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "rollout_flags"


class FlagRequest(BaseModel):
    """A request to turn a branch on: two managers, neither the requester (BR-F9-02)."""

    branch = models.CharField(max_length=30, choices=_choices(FlagBranch))
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.TextField()
    gate_override_reason = models.TextField(blank=True, default="")
    # Values the requester entered for gates that aren't computed, with evidence.
    entered_values = models.JSONField(default=dict)
    gate_snapshot_at_request = models.JSONField(default=list)
    # [{user, at, gate_snapshot, override_reason}]
    approvals = models.JSONField(default=list)
    state = models.CharField(
        max_length=10, choices=_choices(RequestState), default=RequestState.PENDING.value
    )
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "rollout_flag_requests"
        constraints = [
            models.UniqueConstraint(
                fields=["branch"],
                condition=models.Q(state="pending"),
                name="rollout_one_pending_request",
            )
        ]


class RolloutGate(BaseModel):
    """A condition for turning a branch on (BR-F9-04): data, changed by two managers."""

    branch = models.CharField(max_length=30, choices=_choices(FlagBranch))
    phase = models.CharField(max_length=5)
    metric = models.CharField(max_length=30, choices=_choices(GateMetric))
    comparator = models.CharField(max_length=3, choices=_choices(Comparator))
    threshold = models.FloatField()
    window_days = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        db_table = "rollout_gates"
        constraints = [
            models.UniqueConstraint(fields=["branch", "metric"], name="rollout_one_gate_per_metric")
        ]

    def met_by(self, value: float | None) -> bool:
        """Whether `value` passes this gate; no value never does."""
        if value is None:
            return False
        if self.comparator == Comparator.LT.value:
            return value < self.threshold
        return value >= self.threshold


class GateChange(BaseModel):
    """A pending change to a gate, applied when a second manager approves (AC-F9-08)."""

    gate = models.ForeignKey(RolloutGate, on_delete=models.CASCADE, related_name="changes")
    threshold = models.FloatField()
    window_days = models.PositiveSmallIntegerField(null=True, blank=True)
    reason = models.TextField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    state = models.CharField(
        max_length=10, choices=_choices(RequestState), default=RequestState.PENDING.value
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "rollout_gate_changes"


class ThresholdChangeRequest(BaseModel):
    """A full proposed `thresholds.yaml`, approved by two people who aren't its author
    (BR-F9-05, 06)."""

    version = models.CharField(max_length=20, unique=True)
    yaml_text = models.TextField()
    sha256 = models.CharField(max_length=64, db_index=True)
    base_sha256 = models.CharField(max_length=64, blank=True, default="")
    diff = models.TextField(blank=True, default="")
    evidence = models.TextField(blank=True, default="")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # [{user, at, comment}]
    approvals = models.JSONField(default=list)
    state = models.CharField(
        max_length=10, choices=_choices(ChangeState), default=ChangeState.DRAFT.value
    )
    rejected_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    loaded_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "threshold_change_requests"
        ordering = ["-created_at"]
