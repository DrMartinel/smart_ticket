"""
The wire schema core-api speaks to ai-engine (spec §6, ADR-0012): request
and response bodies of `/v1/analyze`, `/v1/embed` and `/v1/pii/detect`.
`AIEngineClient` in `infrastructure/ai_engine.py` sends and parses these;
the router, trust scorer and pipeline read them.

Data only: no I/O, no settings, no decisions. `Branch`, `ReasonCode` and
the other routing types stay in `router.py` (CLAUDE.md rule 4).
"""

from __future__ import annotations


from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from apps.tickets.utils.patterns import PIILevel


# --- Wire schema of POST /v1/analyze (spec §6) --------------------------
#
# ai-engine defines the same shapes in ai_engine/schemas.py. There is no
# shared package: each service is deployed on its own, so change both sides
# in the same PR. Cross-service integration tests are meant to catch drift;
# until they exist, nothing does (ADR-0010).
#
# Every LLM-authored field carries a `proposed_` (or `self_`) prefix. When the
# router reads `draft.proposed_category`, the name itself is the reminder
# that it is a suggestion, not a decision (ADR-0001, ADR-0003). Only
# router.py may write the non-prefixed `category` column on `tickets`.
# `InsufficientContext` is a legitimate variant, not an error path: the
# model needs a lawful way to say "I don't know", or it fabricates.


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
    """
    RootModel because the LLM's output *is* the union, not a wrapper around
    it. `.root` gives back the narrowed instance. The discriminator lets
    Pydantic dispatch by lookup table instead of trying each member in
    turn — faster, and error messages point at the right variant.
    """

    root: LLMProposal


# The final reranker's scale: which model's score `rerank_top1` is on. ai-engine
# always sends "jev" (ADR-0015); the others are for rows stored before it.
# Separate calibrations, never compared across (ADR-0005).
type RerankScorer = Literal["cross_encoder", "lexical", "jev"]


class RetrievalSignals(BaseModel):
    rerank_top1: float = Field(ge=0, le=1)
    rerank_margin: float = Field(ge=0, le=1)  # top1 - top2
    # Where the final reranker's top article (Jev's when it runs) sits in
    # BM25's own article ranking (1 = BM25's best), or None: not in BM25's list, nothing was
    # reranked, or the row predates this field. A RANK, not a BM25 score:
    # BM25 scores are query-dependent and mean nothing across tickets
    # (ADR-0013). The trust scorer turns it into agreement with
    # `retrieval.keyword_agreement_k` from thresholds.yaml.
    bm25_rank_of_top1: int | None = Field(default=None, ge=1)
    # Legacy. The old "BM25 matched anything" flag, which ai-engine no longer
    # sets. It stays, defaulted, so signals stored before ADR-0013 still
    # deserialize and score as they did.
    bm25_keyword_hit: bool = False
    docs_above_floor: int = Field(ge=0)
    # Which model's score `rerank_top1` and `rerank_margin` are on: always
    # Jev's from ai-engine now (ADR-0015). The router compares the floor only
    # when this is "jev", and sends anything else to HITL. Defaults to the
    # cross-encoder so signals stored before ADR-0015 read as what they were.
    scorer: RerankScorer = "cross_encoder"


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
    # A clarify proposal's options are two or more distinct slugs of the
    # chunks the model was shown (ADR-0016). False for every other proposal,
    # and for rows stored before the clarify branch existed.
    clarify_options_in_topk: bool = False


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
    # thresholds.yaml `retrieval.floor`, on Jev's scale (ADR-0015).
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


# --- Wire schema of POST /v1/embed and POST /v1/pii/detect (ADR-0012) ---

# The width of every `vector(1024)` column (bge-m3; ADR-0009). A property of
# the schema, so not configuration: changing it needs a migration.
EMBED_DIM = 1024


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    """`model` is what produced the vector, stored with each ticket
    embedding, so core-api keeps no copy of the embedding model name."""

    vector: list[float]
    model: str


class PiiDetectRequest(BaseModel):
    """RAW, unmasked text: the one exception to "only masked text enters
    ai-engine" (ADR-0012)."""

    text: str


class PiiDetectResponse(BaseModel):
    spans: list[str]
