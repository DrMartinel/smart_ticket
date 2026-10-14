"""
ai-engine settings. Deliberately does NOT read thresholds.yaml: routing
thresholds belong to core-api (spec §1). The retrieval floors ai-engine
needs arrive per-request in `AIRunRequest`, keeping core-api the single
owner of calibration.

Every value comes from the repo root's `.env` (git-ignored; start from
`cp .env.example .env`, the template that documents each setting) or a real
environment variable, which wins. Never from a default in this file, and
never from the template itself. A setting missing from both fails the boot.
The only defaults here are `None`, for the optional secrets and proxy,
meaning "unset".
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root's .env, from services/ai-engine/src/ai_engine/core/config.py.
# Absolute, so it is found whatever the working directory: pytest from the
# repo root, uvicorn from the service. Containers have none (.dockerignore):
# compose hands them its contents as environment variables.
ENV_FILE = Path(__file__).resolve().parents[5] / ".env"


class Settings(BaseSettings):
    # Environment variables win over the file. Empty counts as unset, so an
    # optional secret left blank in .env reads as None.
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_ignore_empty=True, extra="ignore")

    # AI_ENGINE_DATABASE_URL: the read-only role (ADR-0004). DATABASE_URL in
    # the same file is core-api's read-write one.
    database_url: str = Field(validation_alias="AI_ENGINE_DATABASE_URL")
    db_pool_size: int = Field(validation_alias="AI_ENGINE_DB_POOL_SIZE")
    db_max_overflow: int = Field(validation_alias="AI_ENGINE_DB_MAX_OVERFLOW")

    # --- Models ---
    # One provider per job: the proposal, the drafted answer (ADR-0021) and
    # PII NER (ADR-0019).
    chat_client_provider: Literal["vllm", "openai", "deepseek"]
    draft_client_provider: Literal["vllm", "openai", "deepseek"]
    ner_client_provider: Literal["vllm", "deepseek"]
    chat_base_url: str
    chat_model: str
    embed_base_url: str
    embed_model: str
    rerank_base_url: str
    embedding_provider: str
    shortlist_provider: str
    reranker_model: str
    model_timeout_sec: float
    model_connect_timeout_sec: float

    # --- OpenAI ---
    cloud_api_key: str | None = None
    cloud_base_url: str | None = None
    cloud_model: str | None = None
    cloud_max_output_tokens: int

    # --- Versions ---
    graph_version: str
    prompt_version: str
    pii_ner_prompt_version: str
    draft_prompt_version: str

    # --- Retrieval ---
    rrf_k: int
    bm25_top_k: int
    vector_top_k: int
    rerank_top_n: int
    # At most this many of Jev's top `rerank_top_n` from one page.
    rerank_top_n_per_page: int = Field(ge=1)
    fewshot_k: int
    # Distinct pages, not chunks: each page keeps its best-fused chunk.
    fusion_candidate_limit: int
    quote_fuzzy_threshold: float

    # --- Drafted answer (HyDE, ADR-0021) ---
    draft_temperature: float = Field(ge=0)
    # Chunks per candidate page picked by nearness to the draft, beside the
    # page's best-fused chunk.
    draft_chunks_per_page: int = Field(ge=0)

    # --- Link expansion ---
    link_expansion_seeds: int
    link_expansion_chunks_per_page: int
    link_expansion_max_links_per_seed: int
    # The one association source expansion follows (ADR-0018), or "none".
    association_source: Literal["authored_link", "entity_graph", "none"]

    # --- Entity-graph associations: the offline build only (ADR-0018) ---
    association_per_article_cap: int
    entity_graph_policy_version: str
    entity_graph_section_tokens: int
    entity_graph_llm_max_async: int
    entity_graph_resolve_min_similarity: float

    # --- Reranker (Jev) ---
    rerank_pool: int
    jev_base_url: str
    jev_model: str
    jev_api_key: SecretStr | None = None
    rerank_prompt_version: str
    category_question_version: str
    clarify_option_question_version: str


settings = Settings()  # type: ignore[call-arg]  # every value comes from .env or the env
