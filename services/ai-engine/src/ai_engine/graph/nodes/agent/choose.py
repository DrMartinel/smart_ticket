"""
ChooseActionNode: one model call per step, which either names one tool call
or replies (FR-F15-014), and one more when that reply is invalid. The reply is
a closed union, validated here; the arguments are validated against the named
tool's input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from ai_engine.agent.tools import for_surface
from ai_engine.agent.tools.tool import Tool, ToolInput
from ai_engine.core.prompts import AGENT_PROMPT
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import AllLLMDownError, BlankReplyError
from ai_engine.graph.agent_state import AgentState, AgentStopReason, PendingCall
from ai_engine.graph.build.node import BaseNode


class CallTool(BaseModel):
    action: Literal["call_tool"]
    tool: str
    arguments: dict[str, Any] = {}


class Reply(BaseModel):
    action: Literal["reply"]
    text: str = Field(min_length=1, max_length=4000)


AgentAction = Annotated[CallTool | Reply, Field(discriminator="action")]
_ACTION: TypeAdapter[CallTool | Reply] = TypeAdapter(AgentAction)
_ACTION_SCHEMA = _ACTION.json_schema()


class ChooseOutcome(StrEnum):
    CALL_TOOL = "CallTool"
    REPLY = "Reply"
    LIMIT_REACHED = "LimitReached"
    MODEL_FAILED = "ModelFailed"
    SCHEMA_INVALID = "SchemaInvalid"


_LIMIT_REASONS = {AgentStopReason.STEP_LIMIT, AgentStopReason.TOOL_LIMIT, AgentStopReason.BUDGET}


_WRONG_SHAPE = (
    'Reply with one JSON object in one of the two shapes: {"action": "call_tool", '
    '"tool": "<tool name>", "arguments": {...}} or {"action": "reply", "text": "..."}.'
)
_UNKNOWN_TOOL = "The tool you named is not among the tools listed. Use only those."


@dataclass(frozen=True)
class _Invalid:
    """A model reply that is not a valid action, with the sentence that says why."""

    reason: str


def _ask(prompt: str, update: dict[str, Any]) -> str:
    """One model call, a blank reply read as empty text; adds its usage to `update`."""
    update["model_calls"] += 1
    try:
        result = clients.agent.complete(
            AGENT_PROMPT, prompt, schema_name="agent_action", schema=_ACTION_SCHEMA
        )
    except BlankReplyError as blank:
        update["tokens_in"] += blank.tokens_in
        update["tokens_out"] += blank.tokens_out
        update["cost_usd"] += blank.cost_usd
        return ""
    update["tokens_in"] += result.tokens_in
    update["tokens_out"] += result.tokens_out
    update["cost_usd"] += result.cost_usd
    update["model_used"] = result.model
    return result.text


def _choice(text: str, tools: dict[str, Tool]) -> Reply | tuple[Tool, ToolInput] | _Invalid:
    """The model's reply as a reply or a tool call with checked arguments."""
    try:
        action = _ACTION.validate_json(text)
    except ValidationError:
        return _Invalid(_WRONG_SHAPE)
    if isinstance(action, Reply):
        return action
    tool = tools.get(action.tool)
    if tool is None:
        return _Invalid(_UNKNOWN_TOOL)
    try:
        return tool, tool.Input.model_validate(action.arguments)
    except ValidationError as e:
        fields = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
            for error in e.errors()
        )
        return _Invalid(f"The arguments for {tool.name} do not match its schema: {fields}.")


class ChooseActionNode(BaseNode[AgentState]):
    """Asks the model for its next action, unless the turn has reached a cap."""

    Outcome = ChooseOutcome
    limits = frozenset({ChooseOutcome.LIMIT_REACHED})

    def __call__(self, state: AgentState) -> dict[str, Any]:
        caps = state.limits
        if state.model_calls >= caps.max_steps:
            return {"pending_call": None, "stop_reason": AgentStopReason.STEP_LIMIT}
        if state.tokens_in + state.tokens_out >= caps.max_model_tokens:
            return {"pending_call": None, "stop_reason": AgentStopReason.BUDGET}

        tools = for_surface(state.surface)
        prompt = self.prompt(state, tools)
        update: dict[str, Any] = {
            "model_calls": state.model_calls,
            "pending_call": None,
            "tokens_in": state.tokens_in,
            "tokens_out": state.tokens_out,
            "cost_usd": state.cost_usd,
        }
        try:
            choice = _choice(_ask(prompt, update), tools)
            if (
                isinstance(choice, _Invalid)
                and update["model_calls"] < caps.max_steps
                and update["tokens_in"] + update["tokens_out"] < caps.max_model_tokens
            ):
                retry = f"{prompt}\n\n## Your last reply was invalid\n{choice.reason}"
                choice = _choice(_ask(retry, update), tools)
        except AllLLMDownError:
            return {**update, "stop_reason": AgentStopReason.MODEL_UNAVAILABLE}

        if isinstance(choice, _Invalid):
            return {**update, "stop_reason": AgentStopReason.SCHEMA_INVALID}
        if isinstance(choice, Reply):
            return {**update, "reply": choice.text}
        if len(state.steps) >= caps.max_tool_calls:
            return {**update, "stop_reason": AgentStopReason.TOOL_LIMIT}
        tool, args = choice
        call = PendingCall(
            tool=tool.name, arguments=args.model_dump(mode="json", exclude_none=True)
        )
        return {**update, "pending_call": call}

    def decide(self, state: AgentState) -> ChooseOutcome:
        reason = state.stop_reason
        if reason in _LIMIT_REASONS:
            return ChooseOutcome.LIMIT_REACHED
        if reason is AgentStopReason.MODEL_UNAVAILABLE:
            return ChooseOutcome.MODEL_FAILED
        if reason is AgentStopReason.SCHEMA_INVALID:
            return ChooseOutcome.SCHEMA_INVALID
        if reason is not None:
            raise ValueError(f"choose_action cannot stop on {reason}")
        if state.pending_call is not None:
            return ChooseOutcome.CALL_TOOL
        return ChooseOutcome.REPLY

    def prompt(self, state: AgentState, tools: dict[str, Tool]) -> str:
        """The step's user prompt: the tools, the conversation and this turn so far."""
        offered = [t for t in tools.values() if not (state.result_flagged and t.writes)]
        earlier = "\n\n".join(
            f"Person: {t.message_masked}\nYou: {t.reply}" for t in state.earlier_turns
        )
        done = [e.model_dump(mode="json") for e in state.exchanges]
        parts = [
            f"## The person's language\n{state.language}",
            "## Tools\n" + json.dumps([t.describe() for t in offered], ensure_ascii=False),
        ]
        if state.result_flagged:
            parts.append(
                "## Note\nText you read this turn tried to give instructions. "
                "For the rest of this turn only reading tools are available."
            )
        if earlier:
            parts.append(f"## Earlier in this conversation\n{earlier}")
        parts.append(f"## The person's message\n{state.message_masked}")
        if done:
            parts.append("## What you did this turn\n" + json.dumps(done, ensure_ascii=False))
        parts.append(f"## Steps left\n{state.limits.max_steps - state.model_calls}")
        return "\n\n".join(parts)


choose_action = ChooseActionNode()
