"""
ai-engine settings. Deliberately does NOT read config/thresholds.yaml —
that file's routing/business thresholds belong to core-api only (spec §1:
"ai-engine KHÔNG quyết định routing"). The few numeric values ai-engine
does need to make its own refuse-before-LLM decision (retrieval_floor,
budget) arrive per-request in `AIRunRequest`, not from a config file this
service reads on its own — that keeps core-api the single owner of
calibration data.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str = (
        "postgresql://ai_engine_ro:ai_engine_ro_password@localhost:5434/smart_triage"
    )

    ollama_base_url: str = "http://localhost:11434"
    ollama_infer_model: str = "qwen3.5:9b"
    ollama_embed_model: str = "bge-m3"

    embedding_provider: str = "ollama"  # "ollama" | "stub"
    # "cross_encoder" | "lexical". `lexical` is the default: deterministic,
    # fast, and it cannot fail to boot. The cross-encoder is always AVAILABLE
    # — sentence-transformers is a required dependency and the weights ship in
    # the image — so switching is a one-variable change with no rebuild.
    #
    # ⚠️ The two are separate calibrations and `retrieval.floor` is specified
    # against the CROSS-ENCODER distribution (ADR-0005). Under this default it
    # is compared against LexicalReranker's token-overlap ratio instead, which
    # is a different question answered silently. Treat refusal behaviour under
    # `lexical` as uncalibrated. See docs/TODO.md item 4.
    reranker_provider: str = "lexical"

    # Ceiling for any single model call (inference, embeddings). A cold
    # Ollama load can take 15-20s on its own, so a short ceiling reports
    # "provider down" for what is really "provider still warming up".
    # Note this is a CEILING, not a reservation: the per-ticket latency
    # budget in AIRunRequest still bounds the graph as a whole, and
    # infer.py takes whichever of the two is smaller.
    model_timeout_sec: float = 120.0

    # Budgeted separately from the read timeout above: failing to open a
    # TCP connection means the provider is unreachable, which no amount of
    # waiting fixes. Only a reachable-but-busy provider deserves the full
    # read window.
    model_connect_timeout_sec: float = 3.0

    # Lower bound on a single inference attempt's timeout when the ticket's
    # latency budget is nearly spent: a sub-second window guarantees a
    # failure that looks like a provider outage.
    min_attempt_timeout_sec: float = 5.0

    # Cloud provider is optional — if unset, the fallback chain (spec
    # §10.3) goes straight to Ollama, which is this environment's default.
    # Setting cloud_api_key is what ENABLES the cloud primary; cloud_provider
    # only picks which wire protocol it speaks.
    #
    # "openai" is any OpenAI-compatible endpoint and is the only one that
    # needs cloud_base_url. "anthropic" and "gemini" are the first-party APIs
    # and default to their own endpoints. Validated in providers/factory.py —
    # an unknown value is fatal at boot, like every other provider setting.
    cloud_provider: str = "openai"  # "openai" | "anthropic" | "gemini"
    cloud_api_key: str | None = None
    cloud_base_url: str | None = None
    cloud_model: str = "claude-sonnet-5"

    # Ceiling on a single cloud generation. A triage proposal is a small JSON
    # object, so this is well clear of a legitimate reply — it is here to stop
    # a runaway generation from eating the whole per-ticket latency budget.
    # Anthropic in particular defaults to 128000 if left unset.
    cloud_max_output_tokens: int = 4096

    graph_version: str = "v2.1"
    prompt_version: str = "classify.v3"

    rrf_k: int = 60
    bm25_top_k: int = 20
    vector_top_k: int = 20
    rerank_top_n: int = 3
    fewshot_k: int = 3

    # How many post-fusion candidates the reranker actually scores. This is
    # the cross-encoder's batch size, so it is directly a cost/latency knob.
    # It is a SLICE of an RRF-ordered list, never a threshold on the RRF
    # score — ADR-0005.
    fusion_candidate_limit: int = 10

    # The validator's narrow allowance for whitespace/punctuation drift in a
    # verbatim quote — NOT a general "close enough" check (spec §6.4).
    quote_fuzzy_threshold: float = 0.95

    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # The checkpoint, not just the repo. Left at "main" this resolves to
    # whatever BAAI last pushed, and a new commit upstream silently changes
    # the score distribution `retrieval.floor` is calibrated against
    # (ADR-0005) — a drift that does not fail loudly. Pin a commit sha here
    # and in the RERANKER_REVISION build arg; the two must agree, because
    # the image bakes one revision and HF_HUB_OFFLINE=1 makes fetching a
    # different one an error rather than a silent download mid-ticket.
    reranker_revision: str = "main"


settings = Settings()
