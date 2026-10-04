"""
ai-engine's wire contract: the bodies of POST /v1/analyze, /v1/embed and
/v1/pii/detect. Mirrored in core-api's infrastructure/dtos.py, with no shared
package: change both in the same PR (ADR-0010). The graph's own state is in
graph/state.py.
"""

from __future__ import annotations


from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


# --- POST /v1/analyze (spec §6) ------------------------------------------
# No Branch, ReasonCode or TrustScore
# here: ai-engine decides and scores nothing (ADR-0001, ADR-0003).
# LLM-authored fields are prefixed `proposed_`/`self_`: suggestions, not
# decisions.


class PIILevel(StrEnum):
    ROUTINE = "routine"  # proceeds
    SENSITIVE = "sensitive"  # proceeds, flagged
    CRITICAL = "critical"  # BLOCK
    MASK_FAILED = "mask_failed"  # HITL


class TicketCategory(StrEnum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    ACCESS = "access"
    SECURITY = "security"
    OTHER = "other"


class TicketMasked(BaseModel):
    """The only ticket data that enters ai-engine. Frozen: masked content is
    never edited downstream. `placeholder_keys` are keys only, never values."""

    model_config = ConfigDict(frozen=True)

    ticket_public_id: str
    subject_masked: str
    body_masked: str
    pii_level: PIILevel
    placeholder_keys: list[str] = Field(default_factory=list)


class AutoReplyProposal(BaseModel):
    proposed_intent: Literal["auto_reply"]
    kb_slug: str
    verbatim_quote: str = Field(min_length=10, max_length=500)
    answer_draft: str
    self_confidence: float = Field(ge=0, le=100)  # log-only, never routes (ADR-0003)


class RouteProposal(BaseModel):
    proposed_intent: Literal["route_to_team"]
    proposed_category: TicketCategory
    proposed_subcategory: str | None = None
    rationale: str
    self_confidence: float = Field(ge=0, le=100)


class RunbookProposal(BaseModel):
    proposed_intent: Literal["runbook"]
    runbook_id: str
    draft_payload: dict[str, Any]  # never executed directly (ADR-0006)
    proposed_category: TicketCategory
    self_confidence: float = Field(ge=0, le=100)


class InsufficientContext(BaseModel):
    proposed_intent: Literal["insufficient_context"]
    missing_information: str


class ClarificationProposal(BaseModel):
    """Several shown KB pages answer different readings of the ticket, and it
    doesn't say which (ADR-0016). A question for the requester, never an
    answer: core-api's router decides whether it is asked."""

    proposed_intent: Literal["clarify"]
    proposed_question: str = Field(min_length=10, max_length=300)
    # The KB slugs the answer would choose between; the validator checks
    # they were shown (GenerationSignals.clarify_options_in_topk).
    proposed_options: list[str] = Field(min_length=2)
    proposed_category: TicketCategory
    rationale: str


LLMProposal = Annotated[
    AutoReplyProposal
    | RouteProposal
    | RunbookProposal
    | InsufficientContext
    | ClarificationProposal,
    Field(discriminator="proposed_intent"),
]


class LLMProposalEnvelope(RootModel[LLMProposal]):
    """The LLM's output is the union itself; `.root` is the narrowed variant."""

    root: LLMProposal


class RetrievalSignals(BaseModel):
    rerank_top1: float = Field(ge=0, le=1)
    rerank_margin: float = Field(ge=0, le=1)  # top1 - top2
    # BM25's rank of the final top article, or None. A rank, never a BM25
    # score; core-api decides what counts as agreement (ADR-0013).
    bm25_rank_of_top1: int | None = Field(default=None, ge=1)
    # The legacy `bm25_keyword_hit` lives only in core-api's copy, for rows
    # stored before ADR-0013. ai-engine must never set it.
    docs_above_floor: int = Field(ge=0)
    # The scale of the scores above: always Jev's, the reranker
    # (ADR-0015). Sent explicitly: core-api reads a missing value as the
    # cross-encoder's, for rows stored before Jev.
    scorer: Literal["jev"] = "jev"


class GenerationSignals(BaseModel):
    schema_valid: bool
    quote_match_ratio: float = Field(ge=0, le=1)
    quote_source_in_topk: bool
    negation_consistent: bool
    category_consistent: bool  # LLM category vs KB article category
    # False for route/runbook proposals, which have no quote: their zeroed
    # quote checks must not read as failures. Defaulted for older rows.
    quote_applicable: bool = True
    # A clarify proposal's options are two or more distinct slugs of the
    # chunks the model was shown (ADR-0016). False for every other proposal,
    # and for rows stored before the clarify branch existed.
    clarify_options_in_topk: bool = False


class PolicySignals(BaseModel):
    """Hard gates, deliberately NOT part of the trust score."""

    kb_auto_reply_allowed: bool
    kb_risk_tier: str
    pii_level: PIILevel
    injection_detected: bool
    mass_incident: bool


class TrustSignals(BaseModel):
    retrieval: RetrievalSignals
    generation: GenerationSignals
    policy: PolicySignals
    llm_self_confidence: float | None = None  # log-only, never routes (ADR-0003)


class AIRunRequest(BaseModel):
    """Carries only the refuse-before-LLM floor; routing thresholds stay in
    core-api."""

    request_id: str
    ticket: TicketMasked
    # On Jev's scale, compared only with `rerank_score` (ADR-0005, ADR-0015).
    retrieval_floor: float = Field(ge=0, le=1)
    prompt_version: str = "classify.v6"


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


# --- POST /v1/embed and POST /v1/pii/detect (ADR-0012) ---------------------
# core-api's own model calls.


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    vector: list[float]
    model: str  # stored with the vector, so EMBED_MODEL needs no second copy


class PiiDetectRequest(BaseModel):
    """RAW text, the one exception to masked-only input (ADR-0012). Never
    logged, stored or passed into the graph."""

    text: str


class PiiDetectResponse(BaseModel):
    """`[]` means nothing found; a failure is a 502, never `[]`."""

    spans: list[str]
