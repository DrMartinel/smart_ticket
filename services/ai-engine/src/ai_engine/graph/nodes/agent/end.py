"""FinishNode and HandOffNode: the two ways a turn ends."""

from __future__ import annotations

from typing import Any

from ai_engine.graph.agent_state import AgentState
from ai_engine.graph.build.node import BaseNode


class FinishNode(BaseNode[AgentState]):
    """Ends a turn that replied, or that waits for the person to confirm a change."""

    def __call__(self, state: AgentState) -> dict[str, Any]:
        return {}


class HandOffNode(BaseNode[AgentState]):
    """Ends a turn that stopped: whatever the model wrote is dropped (FR-F15-016)."""

    def __call__(self, state: AgentState) -> dict[str, Any]:
        return {"reply": ""}


finish = FinishNode()
hand_off = HandOffNode()
