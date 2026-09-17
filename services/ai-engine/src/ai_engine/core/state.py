"""
TriageState — spec §6.1, as a Pydantic graph schema. Verified against the
installed LangGraph:

- Nodes receive a `TriageState` and return a PARTIAL dict of changed fields.
- The merged state is validated when building the next node's input, so a
  wrong-typed update fails one step later as a 500, which core-api sends to a
  human.
- Update keys that are not fields are silently dropped before validation;
  `extra="forbid"` only guards direct construction, so `GraphBuilder` raises
  on them instead.
- `graph.invoke` returns a plain dict.

Frozen, so an in-place mutation — which would be silently discarded — raises.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from contracts.llm_draft import LLMProposalEnvelope
from contracts.ticket import TicketMasked
from contracts.trust import TrustSignals

from ai_engine.core.retrieval.fusion import Candidate


class RankedChunk(BaseModel):
    """A reranked chunk — spec §6.3. `score` is the cross-encoder score, the
    only one retrieval thresholds may compare against (ADR-0005)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float


class TriageState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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

    # Progressive output. The defaults are what "this node has not run" reads
    # as. List fields deliberately have NO reducer: each is owned by exactly
    # one node, and a validate -> infer retry must overwrite the previous
    # attempt's output, not append to it.

    # InjectionNode
    injection_detected: bool = False
    injection_matched_patterns: list[str] = []

    candidates: list[Candidate] = []  # post-RRF
    bm25_keyword_hit: bool = False  # did lexical search find ANY tsvector match at all
    reranked: list[RankedChunk] = []  # post cross-encoder
    fewshots: list[dict] = []
    proposal: LLMProposalEnvelope | None = None

    # ValidateNode. The defaults read as "every check failed": refuse-before-LLM
    # skips the validator, and a default of anything but "failed" would hand
    # the trust scorer passing checks nobody performed.
    schema_valid: bool = False
    quote_applicable: bool = False
    quote_match_ratio: float = 0.0
    quote_source_in_topk: bool = False
    negation_consistent: bool = False
    category_consistent: bool = False
    source_chunk_id: int | None = None

    # Terminal
    signals: TrustSignals | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_used: str | None = None
    degraded_reason: str | None = None
