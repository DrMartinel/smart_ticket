"""
AgentState (spec F15 §g, §h.6) and the value types the agent graph carries.
Mirrored in core-api's infrastructure/dtos.py, with no shared package:
change both in the same PR (ADR-0010).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AgentLimits(BaseModel):
    """The turn's caps, from core-api's `thresholds.yaml` `agent:` section."""

    model_config = ConfigDict(frozen=True)

    max_steps: int = Field(ge=1)
    max_tool_calls: int = Field(ge=0)
    max_model_tokens: int = Field(ge=1)


class AgentEarlierTurn(BaseModel):
    """An earlier turn of the same agent conversation: the masked message and
    the reply core-api built for it."""

    model_config = ConfigDict(frozen=True)

    message_masked: str
    reply: str


class AgentStopReason(StrEnum):
    """Why a turn handed off. core-api maps each to a `ReasonCode`."""

    STEP_LIMIT = "step_limit"
    TOOL_LIMIT = "tool_limit"
    BUDGET = "budget"
    TOOL_FAILED = "tool_failed"
    TOOL_OUTCOME_UNKNOWN = "tool_outcome_unknown"
    INJECTION = "injection"
    INJECTION_IN_RESULT = "injection_in_result"
    MODEL_UNAVAILABLE = "model_unavailable"
    SCHEMA_INVALID = "schema_invalid"
    TOKEN_REFUSED = "token_refused"


StepOutcome = Literal["ok", "refused", "confirmation_required", "drafted", "failed", "unknown"]


class AgentStep(BaseModel):
    """One tool call: what was sent and what core-api answered. No result body."""

    model_config = ConfigDict(frozen=True)

    seq: int
    tool: str
    arguments: dict[str, Any]
    method: str
    path: str
    status_code: int | None
    outcome: StepOutcome
    action_id: UUID | None = None
    injection_flagged: bool = False


class Exchange(BaseModel):
    """One tool call as the model reads it on its next step: the call and the
    projected result."""

    model_config = ConfigDict(frozen=True)

    tool: str
    arguments: dict[str, Any]
    status: int
    result: Any


class PendingCall(BaseModel):
    """The tool call `choose_action` validated for `call_tool` to make."""

    model_config = ConfigDict(frozen=True)

    tool: str
    arguments: dict[str, Any]


class AgentState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Input
    turn_id: UUID
    surface: Literal["chat", "console"]
    language: Literal["vi", "en"]
    message_masked: str
    earlier_turns: list[AgentEarlierTurn] = []
    limits: AgentLimits
    chat_conversation_id: UUID | None = None
    actor_id: UUID | None = None
    actor_username: str = ""
    token: SecretStr

    # ScreenMessageNode
    injection_detected: bool = False

    # ChooseActionNode
    model_calls: int = 0
    pending_call: PendingCall | None = None
    reply: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_used: str | None = None

    # CallToolNode
    exchanges: list[Exchange] = []
    steps: list[AgentStep] = []
    result_flagged: bool = False  # an untrusted field in some result tripped the screen
    awaiting_confirmation: bool = False

    # Any node that ends the turn early
    stop_reason: AgentStopReason | None = None
