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

    database_url: str = "postgresql://ai_engine_ro:ai_engine_ro_password@localhost:5434/smart_triage"

    ollama_base_url: str = "http://localhost:11434"
    ollama_infer_model: str = "qwen3.5:9b"
    ollama_embed_model: str = "bge-m3"

    embedding_provider: str = "ollama"  # "ollama" | "stub"
    reranker_provider: str = "lexical"  # "cross_encoder" | "lexical"

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

    # Cloud provider is optional — if unset, the fallback chain (spec
    # §10.3) goes straight to Ollama, which is this environment's default.
    cloud_api_key: str | None = None
    cloud_base_url: str | None = None
    cloud_model: str = "claude-sonnet-5"

    graph_version: str = "v2.1"
    prompt_version: str = "classify.v3"

    rrf_k: int = 60
    bm25_top_k: int = 20
    vector_top_k: int = 20
    rerank_top_n: int = 3
    fewshot_k: int = 3


settings = Settings()
