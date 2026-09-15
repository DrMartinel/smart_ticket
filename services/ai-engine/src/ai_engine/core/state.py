"""TriageState — spec §6.1.

Pydantic models, which LangGraph (1.x) supports as a graph schema. What that
does and does not buy, verified against the installed version:

- Each node receives a `TriageState` instance and returns a PARTIAL dict of
  the fields it changed, exactly as before. Returning a whole model would
  overwrite every field.
- LangGraph validates the merged state when it builds the NEXT node's input.
  A node returning a wrong-typed value therefore fails one step later, as a
  ValidationError escaping `graph.invoke` — a 500, which core-api treats as
  `AIEngineUnavailable` and sends to a human. `Terminal` being a real node
  means `emit_signals`' update is validated too.
- An update key that is not a field is silently dropped — by LangGraph,
  before validation, with a TypedDict schema as much as with this one.
  `extra="forbid"` only guards direct construction (tests, `main.py`).
- `graph.invoke` returns a plain dict, not a model.

Frozen: a node that mutated state in place would have its change silently
discarded, so mutation raises instead.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from contracts.llm_draft import LLMProposalEnvelope
from contracts.ticket import TicketMasked
from contracts.trust import TrustSignals


class InjectionVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    detected: bool
    matched_patterns: list[str]


class ValidationResult(BaseModel):
    """No field defaults on purpose: every path through the validate node
    must state each check's outcome, not inherit one by omission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_valid: bool
    quote_applicable: bool
    quote_match_ratio: float
    quote_source_in_topk: bool
    negation_consistent: bool
    category_consistent: bool
    source_chunk_id: int | None = None

    @classmethod
    def all_failed(cls) -> ValidationResult:
        """Every check failed — for "no proposal to validate" and for a
        state in which the validate node never ran."""

        return cls(
            schema_valid=False,
            quote_applicable=False,
            quote_match_ratio=0.0,
            quote_source_in_topk=False,
            negation_consistent=False,
            category_consistent=False,
        )


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
    #
    # `candidates` / `reranked` are `list[Any]`, not `list[Candidate]` /
    # `list[RankedChunk]`: those models live next to the code that produces
    # them, and importing them here would make `core` depend on retrieval and
    # the rerank node.
    injection: InjectionVerdict | None = None
    candidates: list[Any] = []  # ai_engine.retrieval.fusion.Candidate, post-RRF
    bm25_keyword_hit: bool = False  # did lexical search find ANY tsvector match at all
    reranked: list[Any] = []  # ai_engine.graph.nodes.rerank.RankedChunk, post cross-encoder
    fewshots: list[dict] = []
    proposal: LLMProposalEnvelope | None = None
    validation: ValidationResult | None = None

    # Terminal
    signals: TrustSignals | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_used: str | None = None
    degraded_reason: str | None = None
