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
# router reads `proposal.proposed_intent`, the name itself is the reminder
# that it is a suggestion, not a decision (ADR-0001, ADR-0003). Proposals
# carry no category since propose.v8: Jev chooses it (ADR-0017), and only
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
    rationale: str
    self_confidence: float = Field(ge=0, le=100)


class RunbookProposal(BaseModel):
    proposed_intent: Literal["runbook"]
    runbook_id: str
    draft_payload: dict[str, Any]  # NEVER executed directly
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


class RetrievalSignals(BaseModel):
    # Jev's scores, the reranker's (ADR-0015): the scale retrieval.floor is set on.
    rerank_top1: float = Field(ge=0, le=1)
    rerank_margin: float = Field(ge=0, le=1)  # top1 - top2
    # Where Jev's top article sits in BM25's own article ranking (1 = BM25's
    # best), or None: not in BM25's list, or nothing was reranked. A RANK, not a BM25 score:
    # BM25 scores are query-dependent and mean nothing across tickets
    # (ADR-0013). The trust scorer turns it into agreement with
    # `retrieval.keyword_agreement_k` from thresholds.yaml.
    bm25_rank_of_top1: int | None = Field(default=None, ge=1)
    docs_above_floor: int = Field(ge=0)


class GenerationSignals(BaseModel):
    quote_match_ratio: float = Field(ge=0, le=1)
    quote_source_in_topk: bool
    negation_consistent: bool

    # Whether the quote checks above were applicable at all. Only an
    # AutoReplyProposal carries a verbatim quote; a route or runbook
    # proposal has nothing to quote-check, so the validator reports
    # ratio=0.0 / in_topk=False for them. Without this flag those zeros
    # are indistinguishable from a genuine validation failure — which
    # both mis-scores the ticket (see trust_scorer.extract_features) and
    # shows a reviewer two red ✗ marks for checks that never ran.
    quote_applicable: bool = True
    # A clarify proposal's options are two or more distinct slugs of the
    # chunks the model was shown (ADR-0016). False for every other proposal.
    clarify_options_in_topk: bool = False


class PolicySignals(BaseModel):
    """Hard gates. Boolean logic — deliberately NOT part of the trust score."""

    kb_auto_reply_allowed: bool
    kb_risk_tier: str
    pii_level: PIILevel
    injection_detected: bool
    mass_incident: bool


class ClassificationSignals(BaseModel):
    """Jev's answer to the category question (ADR-0017). The router takes
    `category_choice` as the ticket's category; the LLM proposes none
    (propose.v8). No choice (None, 0.0) means Jev wasn't
    asked: a refusal at the injection guard, or a degraded run. The router
    sends that to a human wherever it needs a category.

    No defaults, here or on `EngineSignals.classification`: no signals were
    stored before ADR-0017, so every producer must say what Jev answered."""

    category_choice: TicketCategory | None
    category_confidence: float = Field(ge=0, le=1)


class EngineSignals(BaseModel):
    """What ai-engine found about one ticket: the wire shape of
    `AIRunResponse.signals`. core-api adds what it knows itself (the PII
    level, its own KB read, mass incidents) to build `TrustSignals`
    (`apps/tickets/utils/pipeline.py::trust_signals`)."""

    retrieval: RetrievalSignals
    generation: GenerationSignals
    classification: ClassificationSignals
    injection_detected: bool
    llm_self_confidence: float | None = None  # log-only, never used to route


class TrustSignals(BaseModel):
    """Everything the router and the trust scorer read about one run, and
    what `ai_runs.trust_signals` stores. Built by core-api: ai-engine's
    findings plus `policy`, which is core-api's own."""

    retrieval: RetrievalSignals
    generation: GenerationSignals
    policy: PolicySignals
    classification: ClassificationSignals
    llm_self_confidence: float | None = None  # log-only, never used to route


class AIRunRequest(BaseModel):
    """POST /v1/analyze body. Carries only the threshold the graph needs to
    make a refuse-before-LLM decision (retrieval floor) — routing thresholds
    stay in core-api."""

    request_id: str
    ticket: TicketMasked
    # thresholds.yaml `retrieval.floor`, on Jev's scale (ADR-0015).
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
