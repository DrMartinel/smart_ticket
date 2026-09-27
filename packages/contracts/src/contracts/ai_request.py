"""Wire contract between core-api and ai-engine — spec §6."""

from typing import Any

from pydantic import BaseModel

from contracts.llm_draft import LLMProposalEnvelope
from contracts.ticket import TicketMasked
from contracts.trust import TrustSignals


class AIRunRequest(BaseModel):
    """POST /v1/analyze body. Carries only the threshold the graph needs to
    make a refuse-before-LLM decision (retrieval floor) — routing thresholds
    stay in core-api."""

    request_id: str
    ticket: TicketMasked
    retrieval_floor: float
    prompt_version: str = "classify.v4"


class AIRunResponse(BaseModel):
    request_id: str
    graph_version: str
    prompt_version: str
    model: str
    proposal: LLMProposalEnvelope | None
    signals: TrustSignals
    retrieved_chunks: list[dict[str, Any]] = []
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    degraded_reason: str | None = None
