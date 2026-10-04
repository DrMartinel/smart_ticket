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
    chat_client_provider: Literal["vllm", "openai"]
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

    # --- Retrieval ---
    rrf_k: int
    bm25_top_k: int
    bm25_error_code_boost: float
    vector_top_k: int
    rerank_top_n: int
    fewshot_k: int
    fusion_candidate_limit: int
    quote_fuzzy_threshold: float

    # --- Link expansion ---
    link_expansion_seeds: int
    link_expansion_chunks_per_page: int
    link_expansion_max_links_per_seed: int

    # --- Reranker (Jev) ---
    rerank_pool: int
    jev_base_url: str
    jev_model: str
    jev_api_key: SecretStr | None = None
    rerank_prompt_version: str
    category_question_version: str


settings = Settings()  # type: ignore[call-arg]  # every value comes from .env or the env
