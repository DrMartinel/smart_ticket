"""Routing decision + threshold contracts — spec §8, §13."""

from pydantic import BaseModel, Field

from contracts.enums import Branch, ReasonCode, ReviewQueue, RiskTier, TicketCategory


class KBArticleMeta(BaseModel):
    """The slice of a KB article the router needs. Authority lives here,
    not in anything the LLM says (ADR-0002)."""

    id: int
    slug: str
    category: TicketCategory
    auto_reply_allowed: bool
    risk_tier: RiskTier


class RoutingDecision(BaseModel):
    branch: Branch
    reason_code: ReasonCode
    reason_detail: str = ""
    gate_failed: str | None = None
    trust: float | None = None
    category: TicketCategory | None = None
    kb_slug: str | None = None
    queue: ReviewQueue | None = None
    priority: int = 3
    draft_payload: dict | None = None
    alert_security: bool = False


class RoutingThresholds(BaseModel):
    t_auto: float = Field(ge=0, le=1)
    t_route: float = Field(ge=0, le=1)
    quote_match: float = Field(ge=0, le=1)


class RetrievalThresholds(BaseModel):
    floor: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    bm25_top_k: int
    vector_top_k: int
    rrf_k: int
    rerank_top_n: int


class IncidentThresholds(BaseModel):
    similarity: float = Field(ge=0, le=1)
    window_minutes: int
    min_count: int
    sigma_multiplier: float


class FewshotThresholds(BaseModel):
    max_per_category: int
    ttl_days: int
    min_diversity: float
    require_user_confirmed: bool


class BudgetThresholds(BaseModel):
    max_tokens_per_ticket: int
    max_llm_calls: int
    max_latency_sec: int
    max_graph_iterations: int
    daily_cost_ceiling_usd: float


class AlertThresholds(BaseModel):
    reviewer_approve_rate_max: float
    reviewer_median_time_min_sec: int
    override_rate_delta_max: float
    trust_score_drift_max: float


class Thresholds(BaseModel):
    """Loaded from config/thresholds.yaml. Passed as a parameter everywhere
    it's used — never imported as a global — so it can be varied in tests
    and snapshotted verbatim into `routing_decisions.thresholds_used`."""

    version: str
    calibration_source: str
    routing: RoutingThresholds
    retrieval: RetrievalThresholds
    incident: IncidentThresholds
    fewshot: FewshotThresholds
    budget: BudgetThresholds
    alerts: AlertThresholds

    @property
    def retrieval_floor(self) -> float:
        return self.retrieval.floor

    @property
    def t_auto(self) -> float:
        return self.routing.t_auto

    @property
    def t_route(self) -> float:
        return self.routing.t_route

    @property
    def quote_match(self) -> float:
        return self.routing.quote_match
