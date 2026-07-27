"""Wire contract between core-api and ai-engine — spec §6."""

from pydantic import BaseModel

from contracts.llm_draft import LLMProposalEnvelope
from contracts.ticket import TicketMasked
from contracts.trust import TrustSignals


class AIRunRequest(BaseModel):
    """POST /v1/analyze body. `thresholds_snapshot` only carries the pieces
    the graph needs to make a refuse-before-LLM decision (retrieval floor,
    budget) — routing thresholds stay in core-api."""

    request_id: str
    ticket: TicketMasked
    retrieval_floor: float
    max_tokens: int
    max_llm_calls: int
    max_latency_sec: int
    max_graph_iterations: int
    prompt_version: str = "classify.v3"


class AIRunResponse(BaseModel):
    request_id: str
    graph_version: str
    prompt_version: str
    model: str
    proposal: LLMProposalEnvelope | None
    signals: TrustSignals
    retrieved_chunks: list[dict] = []
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    degraded_reason: str | None = None
