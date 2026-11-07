"""
Mask guard: sends a ticket whose masking failed straight to `emit_signals`,
so no model past the injection guard sees its text.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.state import TriageState
from ai_engine.graph.ticket import PIILevel


class MaskGuardOutcome(StrEnum):
    MASK_FAILED = "MaskFailed"
    MASKED = "Masked"


class MaskGuardNode(BaseNode[TriageState]):
    """A `mask_failed` ticket goes to `emit_signals`; every other one to the drafting model."""

    Outcome = MaskGuardOutcome

    def __call__(self, state: TriageState) -> dict[str, Any]:
        return {}

    def decide(self, state: TriageState) -> MaskGuardOutcome:
        if state.ticket.pii_level is PIILevel.MASK_FAILED:
            return MaskGuardOutcome.MASK_FAILED
        return MaskGuardOutcome.MASKED


mask_guard = MaskGuardNode()
