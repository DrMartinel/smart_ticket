"""What the Rollout and Thresholds pages show (F9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Schema

from apps.rollout.models import GateChange, RolloutFlag, ThresholdChangeRequest
from apps.rollout.utils.gates import Agreement, GateValue


class GateValueOut(Schema):
    metric: str
    comparator: str
    threshold: float
    window_days: int | None
    phase: str
    value: float | None
    met: bool
    entered: bool
    evidence: str


class GateOut(Schema):
    id: uuid.UUID
    branch: str
    phase: str
    metric: str
    comparator: str
    threshold: float
    window_days: int | None


class GateChangeOut(Schema):
    id: uuid.UUID
    gate: uuid.UUID
    threshold: float
    window_days: int | None
    reason: str
    requested_by: str
    state: str
    created_at: datetime

    @classmethod
    def of(cls, change: GateChange) -> GateChangeOut:
        return cls(
            id=change.id,
            gate=change.gate_id,
            threshold=change.threshold,
            window_days=change.window_days,
            reason=change.reason,
            requested_by=change.requested_by.username,
            state=change.state,
            created_at=change.created_at,
        )


class FlagOut(Schema):
    branch: str
    state: str
    live: bool
    changed_by: str | None
    changed_at: datetime | None
    reason: str
    gates: list[GateValueOut]
    # Shadow decisions of the branch a reviewer agreed with ÷ those decided (BR-F10-10).
    agreement: float | None
    agreement_decided: int

    @classmethod
    def of(
        cls,
        flag: RolloutFlag,
        live: bool,
        gates: list[GateValue],
        agreement: Agreement,
    ) -> FlagOut:
        return cls(
            branch=flag.branch,
            state=flag.state,
            live=live,
            changed_by=flag.changed_by.username if flag.changed_by else None,
            changed_at=flag.changed_at,
            reason=flag.reason,
            gates=[GateValueOut(**g.as_json()) for g in gates],
            agreement=agreement.rate,
            agreement_decided=agreement.decided,
        )


class ThresholdsStatusOut(Schema):
    version: str
    sha256: str
    approved: bool
    checked: bool
    change_request: str | None


class RolloutOut(Schema):
    env_shadow: bool
    thresholds: ThresholdsStatusOut
    flags: list[FlagOut]
    gates: list[GateOut]


class ChangeRequestOut(Schema):
    id: uuid.UUID
    version: str
    sha256: str
    base_sha256: str
    diff: str
    evidence: str
    author: str | None
    approvals: list[dict[str, Any]]
    state: str
    rejected_reason: str
    created_at: datetime
    submitted_at: datetime | None
    approved_at: datetime | None
    loaded_at: datetime | None

    @classmethod
    def of(cls, request: ThresholdChangeRequest) -> ChangeRequestOut:
        return cls(**cls.fields_of(request))

    @staticmethod
    def fields_of(request: ThresholdChangeRequest) -> dict[str, Any]:
        return {
            "id": request.id,
            "version": request.version,
            "sha256": request.sha256,
            "base_sha256": request.base_sha256,
            "diff": request.diff,
            "evidence": request.evidence,
            "author": request.author.username if request.author else None,
            "approvals": request.approvals,
            "state": request.state,
            "rejected_reason": request.rejected_reason,
            "created_at": request.created_at,
            "submitted_at": request.submitted_at,
            "approved_at": request.approved_at,
            "loaded_at": request.loaded_at,
        }


class ChangeRequestDetailOut(ChangeRequestOut):
    yaml_text: str

    @classmethod
    def detail(cls, request: ThresholdChangeRequest) -> ChangeRequestDetailOut:
        return cls(**ChangeRequestOut.fields_of(request), yaml_text=request.yaml_text)


class CurrentThresholdsOut(Schema):
    version: str
    sha256: str
    approved: bool
    checked: bool
    change_request: str | None
    loaded_at: datetime | None
    next_version: str
    yaml: str
