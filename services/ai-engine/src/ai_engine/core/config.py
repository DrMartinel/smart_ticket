"""
ai-engine settings. Deliberately does NOT read thresholds.yaml: routing
thresholds belong to core-api (spec §1). The few numbers ai-engine needs
(retrieval_floor, budget) arrive per-request in `AIRunRequest`, keeping
core-api the single owner of calibration.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str = (
        "postgresql://ai_engine_ro:ai_engine_ro_password@localhost:5434/smart_triage"
    )

    # The LLM clients (built at the bottom of providers/llm/models.py).
    # Embeddings and reranking always run on self-hosted vLLM (ADR-0009), which
    # serves one model per server — see the `vllm` profile in
    # infra/docker-compose.yml. Chat runs on `chat_client_provider`: "vllm"
    # uses chat_model / chat_base_url; the cloud providers "openai" |
    # "anthropic" | "gemini" read the cloud_* settings. Anything else fails
    # here, at boot.
    chat_client_provider: Literal["vllm", "openai", "anthropic", "gemini"] = "vllm"
    chat_base_url: str = "http://localhost:8100/v1"
    chat_model: str = "Qwen/Qwen3-8B-AWQ"
    embed_base_url: str = "http://localhost:8101/v1"
    # Must be the model AND runtime the KB chunks in pgvector were embedded
    # with, and the same one core-api's EMBED_MODEL uses. Vectors stored
    # from Ollama must be re-embedded before trusting retrieval (ADR-0009).
    embed_model: str = "BAAI/bge-m3"
    rerank_base_url: str = "http://localhost:8102/v1"

    # "vllm" | "stub". "stub" is deterministic and offline, for CI.
    embedding_provider: str = "vllm"
    # "vllm" | "lexical". "vllm" serves the `reranker_model` cross-encoder
    # from self-hosted vLLM (ADR-0009). "lexical" is deterministic, offline and
    # dependency-free, for CI.
    #
    # ⚠️ They are separate calibrations and `retrieval.floor` is specified
    # against the CROSS-ENCODER distribution (ADR-0005). Under `lexical` it is
    # compared against a token-overlap ratio instead, which is a different
    # question answered silently. Treat refusal behaviour under `lexical` as
    # uncalibrated. See docs/TODO.md item 4.
    reranker_provider: str = "vllm"

    # Ceiling for any single model call (inference, embeddings, rerank). A
    # cold model load can take 15-20s on its own, so a short ceiling reports
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

    # The cloud chat APIs, used when chat_client_provider is "openai",
    # "anthropic" or "gemini". cloud_base_url is an optional proxy for
    # "openai" and "anthropic" and is rejected for "gemini". Validated in providers/llm/models.py — any
    # misconfiguration is fatal at boot.
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
    # the reranker's batch size, so it is directly a cost/latency knob.
    # It is a SLICE of an RRF-ordered list, never a threshold on the RRF
    # score — ADR-0005.
    fusion_candidate_limit: int = 10

    # The validator's narrow allowance for whitespace/punctuation drift in a
    # verbatim quote — NOT a general "close enough" check (spec §6.4).
    quote_fuzzy_threshold: float = 0.95

    # The model name sent to vllm-rerank. The checkpoint revision is pinned
    # where the model is loaded — RERANKER_REVISION on the vllm-rerank service
    # (ADR-0005: an upstream commit must not silently move the score scale).
    reranker_model: str = "BAAI/bge-reranker-v2-m3"


settings = Settings()
