"""
ai-engine's HTTP bodies: the requests and responses of POST /v1/analyze,
/v1/embed and /v1/pii/detect, and nothing else. What they carry is the
graph's: the ticket (graph/ticket.py), the proposal
(graph/nodes/infer/proposals.py) and the signals
(graph/nodes/emit_signals/signals.py). The graph never imports this module.
Mirrored in core-api's infrastructure/dtos.py, with no shared package:
change both in the same PR (ADR-0010).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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
    prompt_version: str = "propose.v8"


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
