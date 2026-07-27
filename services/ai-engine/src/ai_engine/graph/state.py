"""TriageState — spec §6.1."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from contracts.llm_draft import LLMProposalEnvelope
from contracts.ticket import TicketMasked
from contracts.trust import TrustSignals


class InjectionVerdict(TypedDict):
    detected: bool
    matched_patterns: list[str]


class ValidationResult(TypedDict):
    schema_valid: bool
    quote_applicable: bool
    quote_match_ratio: float
    quote_source_in_topk: bool
    negation_consistent: bool
    category_consistent: bool
    source_chunk_id: NotRequired[int]


class TriageState(TypedDict):
    # Input (immutable)
    ticket: TicketMasked
    request_id: str
    retrieval_floor: float
    max_tokens: int
    max_llm_calls: int
    max_latency_sec: int
    max_graph_iterations: int

    # Budget tracking — checked at every expensive node
    tokens_used: int
    llm_calls: int
    started_at: float
    iteration: int

    # Progressive output
    injection: NotRequired[InjectionVerdict]
    candidates: NotRequired[list[Any]]  # ai_engine.retrieval.fusion.Candidate, post-RRF
    bm25_keyword_hit: NotRequired[bool]  # did lexical search find ANY tsvector match at all
    reranked: NotRequired[list[Any]]  # (Candidate, score) pairs, post cross-encoder
    fewshots: NotRequired[list[dict]]
    proposal: NotRequired[LLMProposalEnvelope | None]
    validation: NotRequired[ValidationResult]

    # Terminal
    signals: NotRequired[TrustSignals]
    tokens_in: NotRequired[int]
    tokens_out: NotRequired[int]
    cost_usd: NotRequired[float]
    model_used: NotRequired[str]
    degraded_reason: NotRequired[str | None]
