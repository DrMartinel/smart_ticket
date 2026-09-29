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

import uuid

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from ai_engine.core.retrieval.fusion import Candidate


# --- Wire schema of POST /v1/analyze (spec §6) --------------------------
#
# core-api defines the same shapes in infrastructure/ai_engine.py. There is
# no shared package: each service is deployed on its own, so change both
# sides in the same PR. Cross-service integration tests are meant to catch
# drift; until they exist, nothing does (ADR-0010).
# Only what crosses the wire lives here: no Branch, ReasonCode or TrustScore,
# because ai-engine decides nothing and does not score itself (ADR-0001,
# ADR-0003).
#
# Every LLM-authored field carries a `proposed_` (or `self_`) prefix: the
# name is the reminder that the value is a suggestion, not a decision.


class PIILevel(StrEnum):
    ROUTINE = "routine"  # name, internal email, employee code → proceeds
    SENSITIVE = "sensitive"  # national ID, bank account, health → proceeds, flagged
    CRITICAL = "critical"  # password / token / API key → BLOCK
    MASK_FAILED = "mask_failed"  # masker errored / uncertain → HITL


class TicketCategory(StrEnum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    ACCESS = "access"
    SECURITY = "security"
    OTHER = "other"


class TicketMasked(BaseModel):
    """The only thing allowed to flow into the AI engine.

    `frozen=True` is deliberate: once masked, nothing downstream may edit the
    content. `placeholder_keys` carries keys only ("[EMAIL_1]"), never
    values — recovering a real value requires the quarantine endpoint and
    is logged (`pii_access_log`).
    """

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
    self_confidence: float = Field(ge=0, le=100)  # log-only, never used to route


class RouteProposal(BaseModel):
    proposed_intent: Literal["route_to_team"]
    proposed_category: TicketCategory
    proposed_subcategory: str | None = None
    rationale: str
    self_confidence: float = Field(ge=0, le=100)


class RunbookProposal(BaseModel):
    proposed_intent: Literal["runbook"]
    runbook_id: str
    draft_payload: dict[str, Any]  # NEVER executed directly
    proposed_category: TicketCategory
    self_confidence: float = Field(ge=0, le=100)


class InsufficientContext(BaseModel):
    proposed_intent: Literal["insufficient_context"]
    missing_information: str


LLMProposal = Annotated[
    AutoReplyProposal | RouteProposal | RunbookProposal | InsufficientContext,
    Field(discriminator="proposed_intent"),
]


class LLMProposalEnvelope(RootModel[LLMProposal]):
    """
    RootModel because the LLM's output *is* the union, not a wrapper around
    it. `.root` gives back the narrowed instance. The discriminator lets
    Pydantic dispatch by lookup table instead of trying each member in
    turn — faster, and error messages point at the right variant.
    """

    root: LLMProposal


class RetrievalSignals(BaseModel):
    rerank_top1: float = Field(ge=0, le=1)
    rerank_margin: float = Field(ge=0, le=1)  # top1 - top2
    bm25_keyword_hit: bool
    docs_above_floor: int = Field(ge=0)
    topk_chunk_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])


class GenerationSignals(BaseModel):
    schema_valid: bool
    quote_match_ratio: float = Field(ge=0, le=1)
    quote_source_in_topk: bool
    negation_consistent: bool
    category_consistent: bool  # LLM category vs KB article category

    # Whether the quote checks above were applicable at all. Only an
    # AutoReplyProposal carries a verbatim quote; a route or runbook
    # proposal has nothing to quote-check, so the validator reports
    # ratio=0.0 / in_topk=False for them. Without this flag those zeros
    # are indistinguishable from a genuine validation failure — which
    # both mis-scores the ticket (see trust_scorer.extract_features) and
    # shows a reviewer two red ✗ marks for checks that never ran.
    # Defaults True so older persisted signals deserialize unchanged.
    quote_applicable: bool = True


class PolicySignals(BaseModel):
    """Hard gates. Boolean logic — deliberately NOT part of the trust score."""

    kb_auto_reply_allowed: bool
    kb_risk_tier: str
    pii_level: PIILevel
    injection_detected: bool
    mass_incident: bool


class TrustSignals(BaseModel):
    retrieval: RetrievalSignals
    generation: GenerationSignals
    policy: PolicySignals
    llm_self_confidence: float | None = None  # log-only, never used to route


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


class RankedChunk(BaseModel):
    """A reranked chunk — spec §6.3. `score` is the cross-encoder score, the
    only one retrieval thresholds may compare against (ADR-0005)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    article_id: uuid.UUID
    article_slug: str
    content: str
    score: float


class TriageState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Input (immutable)
    ticket: TicketMasked
    request_id: str
    retrieval_floor: float

    # Progressive output. The defaults are what "this node has not run" reads
    # as. List fields deliberately have NO reducer: each is owned by exactly
    # one node.

    # InjectionNode
    injection_detected: bool = False
    injection_matched_patterns: list[str] = []

    # HybridRetrieveNode
    bm25_keyword_hit: bool = False
    candidates: list[Candidate] = []  # post-RRF

    # RerankNode
    reranked: list[RankedChunk] = []

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
    schema_valid: bool = False
    quote_applicable: bool = False
    quote_match_ratio: float = 0.0
    quote_source_in_topk: bool = False
    negation_consistent: bool = False
    category_consistent: bool = False
    source_chunk_id: uuid.UUID | None = None

    # EmitSignalsNode
    signals: TrustSignals | None = None
