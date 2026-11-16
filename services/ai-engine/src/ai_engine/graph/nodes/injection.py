"""
Injection detector — spec §6.2 `detect_inject`. Runs FIRST, before any
retrieval or LLM cost. Attachments are fully untrusted (spec §5.2) and never
fetched, so nothing from one reaches the prompt.
"""

from __future__ import annotations

from typing import Any

from enum import StrEnum

from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.injection_patterns import matches
from ai_engine.graph.state import TriageState


class InjectionOutcome(StrEnum):
    INJECTION_DETECTED = "InjectionDetected"
    INJECTION_CLEAR = "InjectionClear"


class InjectionNode(BaseNode[TriageState]):
    """Prompt-injection screen. A hit routes straight to `EmitSignalsNode`,
    spending no further tokens.
    """

    Outcome = InjectionOutcome

    def __call__(self, state: TriageState) -> dict[str, Any]:
        text = f"{state.ticket.subject_masked}\n{state.ticket.body_masked}"
        return {"injection_detected": bool(matches(text))}

    def decide(self, state: TriageState) -> InjectionOutcome:
        if state.injection_detected:
            return InjectionOutcome.INJECTION_DETECTED
        return InjectionOutcome.INJECTION_CLEAR


injection = InjectionNode()
