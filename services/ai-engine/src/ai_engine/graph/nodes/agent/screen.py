"""ScreenMessageNode: the person's masked message, screened before any model call (FR-F15-011)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ai_engine.graph.agent_state import AgentState, AgentStopReason
from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.injection_patterns import matches


class ScreenOutcome(StrEnum):
    CLEAR = "Clear"
    INJECTION_DETECTED = "InjectionDetected"


class ScreenMessageNode(BaseNode[AgentState]):
    """Stops the turn when the person's message trips an injection pattern."""

    Outcome = ScreenOutcome

    def __call__(self, state: AgentState) -> dict[str, Any]:
        if matches(state.message_masked):
            return {"injection_detected": True, "stop_reason": AgentStopReason.INJECTION}
        return {}

    def decide(self, state: AgentState) -> ScreenOutcome:
        if state.injection_detected:
            return ScreenOutcome.INJECTION_DETECTED
        return ScreenOutcome.CLEAR


screen_message = ScreenMessageNode()
