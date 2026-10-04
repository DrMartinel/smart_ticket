"""
TriageState (spec §6.1) and the value types stored in it. Nodes return
partial dicts; LangGraph validates the merged state before the next node, so
a wrong-typed update fails the run (500 → HITL). Frozen: an in-place mutation
would be silently discarded, so it raises instead.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from ai_engine.graph.nodes.emit_signals.signals import EngineSignals
from ai_engine.graph.nodes.infer.proposals import LLMProposalEnvelope
from ai_engine.graph.ticket import TicketCategory, TicketMasked


class Candidate(BaseModel):
    """A fused retrieval hit. Carries no score: the RRF score only orders
    the list, so nothing can threshold against it (ADR-0005)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    article_id: uuid.UUID
    article_slug: str
    content: str


class RankedChunk(BaseModel):
    """A chunk with one score per reranking stage (never an RRF score,
    ADR-0005). `shortlist_score`: the cross-encoder's (lexical in CI), which
    orders the pool and picks Jev's shortlist. `rerank_score`: Jev's, the
    final one, None until Jev scores the chunk. Compare thresholds only
    through `final_score`."""

    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    article_id: uuid.UUID
    article_slug: str
    content: str
    shortlist_score: float
    rerank_score: float | None = None

    def final_score(self) -> float:
        """Raises when Jev hasn't scored the chunk: falling back to the
        cross-encoder's would compare it with the Jev floor (ADR-0015)."""
        if self.rerank_score is None:
            raise ValueError(f"chunk {self.chunk_id} has no Jev score")
        return self.rerank_score


class TriageState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Input
    ticket: TicketMasked
    request_id: str
    retrieval_floor: float

    # InjectionNode
    injection_detected: bool = False

    # HybridRetrieveNode
    bm25_article_ids: list[uuid.UUID] = []  # best first, for agreement
    candidates: list[Candidate] = []  # post-RRF
    query_embedding: list[float] = []  # reused by link expansion and few-shots

    # CandidatePoolNode
    pool: list[RankedChunk] = []  # cross-encoder order, Jev's shortlist first

    # RerankNode
    reranked: list[RankedChunk] = []  # Jev order, every one Jev-scored

    # ClassifyCategoryNode
    category_choice: TicketCategory | None = None
    category_confidence: float = 0.0

    # SelectFewshotsNode
    fewshots: list[dict[str, Any]] = []

    # InferNode
    proposal: LLMProposalEnvelope | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_used: str | None = None
    degraded_reason: str | None = None

    # ValidateNode
    quote_applicable: bool = False
    quote_match_ratio: float = 0.0
    quote_source_in_topk: bool = False
    negation_consistent: bool = False
    clarify_options_in_topk: bool = False

    # EmitSignalsNode
    signals: EngineSignals | None = None
