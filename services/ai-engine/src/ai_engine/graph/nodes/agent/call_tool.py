"""
CallToolNode: makes the one call `choose_action` validated, as the person,
and turns core-api's answer into a step for core-api's record and an
exchange for the model's next step (FR-F15-012, FR-F15-013).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from ai_engine.agent.tools import TOOLS
from ai_engine.agent.tools import client as tool_client
from ai_engine.agent.tools.client import OutcomeUnknown, Reply, ToolFailed
from ai_engine.agent.tools.projection import flagged, refusal
from ai_engine.agent.tools.tool import Context, Tier, Tool
from ai_engine.graph.agent_state import (
    AgentState,
    AgentStep,
    AgentStopReason,
    Exchange,
    StepOutcome,
)
from ai_engine.graph.build.node import BaseNode


class CallOutcome(StrEnum):
    RESULT = "Result"
    DRAFTED = "Drafted"
    AWAITING_CONFIRMATION = "AwaitingConfirmation"
    FAILED = "Failed"
    OUTCOME_UNKNOWN = "OutcomeUnknown"


class CallToolNode(BaseNode[AgentState]):
    """One HTTP call to core-api, never retried."""

    Outcome = CallOutcome

    def __call__(self, state: AgentState) -> dict[str, Any]:
        if state.pending_call is None:
            raise ValueError("call_tool ran with no pending call")
        tool = TOOLS[state.pending_call.tool]
        if state.result_flagged and tool.writes:
            return {"stop_reason": AgentStopReason.INJECTION_IN_RESULT}

        arguments = state.pending_call.arguments
        args = tool.Input.model_validate(arguments)
        context = Context(
            token=state.token,
            actor_id=state.actor_id,
            actor_username=state.actor_username,
            chat_conversation_id=state.chat_conversation_id,
        )
        step = {"seq": len(state.steps) + 1, "tool": tool.name, "arguments": arguments}
        step["method"], step["path"] = tool.method, tool.path_for(arguments)
        try:
            step["path"], reply = tool.run(tool_client.core_api, args, context)
        except ToolFailed:
            return self.stop(state, step, AgentStopReason.TOOL_FAILED, "failed")
        except OutcomeUnknown:
            return self.stop(state, step, AgentStopReason.TOOL_OUTCOME_UNKNOWN, "unknown")
        step["status_code"] = reply.status

        if reply.status == 401:
            return self.stop(state, step, AgentStopReason.TOKEN_REFUSED, "failed")
        if reply.status == 429:
            return self.stop(state, step, AgentStopReason.TOOL_LIMIT, "refused")
        if tool.tier is Tier.CONFIRM and reply.status == 202:
            if (action := self.action_id(reply.body, "action_id")) is None:
                return self.stop(state, step, AgentStopReason.TOOL_FAILED, "failed")
            result = {"action_id": str(action), "state": "awaiting_confirmation"}
            return {
                **self.record(state, step, "confirmation_required", tool, reply, result, action),
                "awaiting_confirmation": True,
            }
        if tool.tier is Tier.HUMAN_ONLY and self.is_draft(reply):
            details = reply.body.get("details") or {}
            if (draft := self.action_id(details, "draft_id")) is None:
                return self.stop(state, step, AgentStopReason.TOOL_FAILED, "failed")
            result = {
                "draft_id": str(draft),
                "state": "draft_waiting",
                "meaning": "Nothing changed. A draft waits for the person to apply on the item's page.",
            }
            return self.record(state, step, "drafted", tool, reply, result, draft)
        if 200 <= reply.status < 300:
            projected = tool.project(reply.body, context)
            return self.record(state, step, "ok", tool, reply, projected, None)
        return self.record(state, step, "refused", tool, reply, refusal(reply.body), None)

    def decide(self, state: AgentState) -> CallOutcome:
        if state.stop_reason is AgentStopReason.TOOL_OUTCOME_UNKNOWN:
            return CallOutcome.OUTCOME_UNKNOWN
        if state.stop_reason is not None:
            return CallOutcome.FAILED
        if state.awaiting_confirmation:
            return CallOutcome.AWAITING_CONFIRMATION
        if state.steps and state.steps[-1].outcome == "drafted":
            return CallOutcome.DRAFTED
        return CallOutcome.RESULT

    def record(
        self,
        state: AgentState,
        step: dict[str, Any],
        outcome: StepOutcome,
        tool: Tool,
        reply: Reply,
        result: Any,
        action: UUID | None,
    ) -> dict[str, Any]:
        """The step and the exchange for a call core-api answered."""
        flag = outcome == "ok" and flagged(result)
        done = AgentStep(**step, outcome=outcome, action_id=action, injection_flagged=flag)
        exchange = Exchange(
            tool=tool.name, arguments=step["arguments"], status=reply.status, result=result
        )
        update: dict[str, Any] = {
            "steps": [*state.steps, done],
            "exchanges": [*state.exchanges, exchange],
        }
        if flag:
            update["result_flagged"] = True
        return update

    def stop(
        self,
        state: AgentState,
        step: dict[str, Any],
        reason: AgentStopReason,
        outcome: StepOutcome,
    ) -> dict[str, Any]:
        """The step for a call that ends the turn."""
        done = AgentStep(**{"status_code": None, **step}, outcome=outcome)
        return {"steps": [*state.steps, done], "stop_reason": reason}

    def is_draft(self, reply: Reply) -> bool:
        """Whether core-api stored a draft instead of running a human_only route."""
        return (
            reply.status == 403
            and isinstance(reply.body, dict)
            and reply.body.get("code") == "human_only_action"
        )

    def action_id(self, body: Any, key: str) -> UUID | None:
        """The stored action's id in core-api's answer."""
        try:
            return UUID(str(body[key]))
        except (KeyError, TypeError, ValueError):
            return None


call_tool = CallToolNode()
