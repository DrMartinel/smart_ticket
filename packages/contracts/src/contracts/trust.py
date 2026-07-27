"""Trust signals — spec §4.4."""

from pydantic import BaseModel, Field

from contracts.enums import PIILevel


class RetrievalSignals(BaseModel):
    rerank_top1: float = Field(ge=0, le=1)
    rerank_margin: float = Field(ge=0, le=1)  # top1 - top2
    bm25_keyword_hit: bool
    docs_above_floor: int = Field(ge=0)
    topk_chunk_ids: list[int] = Field(default_factory=list)


class GenerationSignals(BaseModel):
    schema_valid: bool
    quote_match_ratio: float = Field(ge=0, le=1)
    quote_source_in_topk: bool
    negation_consistent: bool
    category_consistent: bool  # LLM category vs KB article category


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


class TrustScore(BaseModel):
    value: float = Field(ge=0, le=1)
    model_version: str  # e.g. "logreg-v2-2026-07"
    contributions: dict[str, float] = Field(default_factory=dict)  # UI explainability
