"""What the Rollout and Thresholds pages show (F9)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from django.conf import settings
from ninja import Schema

from apps.rollout.models import GateChange, RolloutFlag
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


class RolloutOut(Schema):
    env_shadow: bool
    thresholds: str
    flags: list[FlagOut]
    gates: list[GateOut]


class CurrentThresholdsOut(Schema):
    version: str
    sha256: str
    yaml: str

    @classmethod
    def loaded(cls) -> CurrentThresholdsOut:
        """The thresholds.yaml core-api loaded."""
        with open(settings.THRESHOLDS_PATH, encoding="utf-8") as f:
            text = f.read()
        return cls(
            version=settings.THRESHOLDS.version,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            yaml=text,
        )
