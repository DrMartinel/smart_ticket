"""
ai-engine's HTTP bodies: the requests and responses of POST /v1/analyze,
/v1/embed, /v1/pii/detect and /v1/agent/turn, and nothing else. What they
carry is the graphs': the ticket (graph/ticket.py), the proposal
(graph/nodes/infer/proposals.py), the signals
(graph/nodes/emit_signals/signals.py) and the agent's steps
(graph/agent_state.py). The graph never imports this module.
Mirrored in core-api's infrastructure/dtos.py, with no shared package:
change both in the same PR (ADR-0010).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr

from ai_engine.graph.agent_state import AgentEarlierTurn, AgentLimits, AgentStep, AgentStopReason

from ai_engine.graph.nodes.emit_signals.signals import EngineSignals
from ai_engine.graph.nodes.infer.proposals import LLMProposalEnvelope
from ai_engine.graph.ticket import TicketMasked


# --- POST /v1/analyze (spec §6) ------------------------------------------


class AIRunRequest(BaseModel):
    """Carries only the refuse-before-LLM floor; routing thresholds stay in
    core-api."""

    request_id: str
    ticket: TicketMasked
    retrieval_floor: float = Field(ge=0, le=1)
    prompt_version: str = "propose.v10"


class AIRunResponse(BaseModel):
    request_id: str
    graph_version: str
    prompt_version: str
    model: str
    proposal: LLMProposalEnvelope | None
    signals: EngineSignals
    retrieved_chunks: list[dict[str, Any]] = []
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    degraded_reason: str | None = None


# --- POST /v1/embed and POST /v1/pii/detect (ADR-0012) ---------------------
# core-api's own model calls.


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    vector: list[float]
    model: str


class PiiDetectRequest(BaseModel):
    """RAW text, the one exception to masked-only input (ADR-0012). Never
    logged, stored or passed into the graph."""

    text: str


class PiiDetectResponse(BaseModel):
    """`[]` means nothing found; a failure is a 502, never `[]`."""

    spans: list[str]


# --- POST /v1/agent/turn (F15, ADR-0046) -------------------------------------


class AgentTurnRequest(BaseModel):
    """One agent turn. Carries the surface's tool set, never the person's
    permissions (BR-F15-16). `actor_id` and `actor_username` let code show
    the person as `you`; they never reach the model."""

    turn_id: UUID
    surface: Literal["chat", "console"]
    language: Literal["vi", "en"]
    message_masked: str
    earlier_turns: list[AgentEarlierTurn] = Field(default_factory=list)
    limits: AgentLimits
    chat_conversation_id: UUID | None = None
    actor_id: UUID | None = None
    actor_username: str = ""
    token: SecretStr


AgentOutcome = Literal["replied", "awaiting_confirmation", "handed_off"]


class AgentTurnResponse(BaseModel):
    outcome: AgentOutcome
    reply: str = ""
    stop_reason: AgentStopReason | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
