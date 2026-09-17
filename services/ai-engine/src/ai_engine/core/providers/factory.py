"""
The single place provider selection happens — once, at startup, with any
unknown value fatal. A silent fallback (a typo'd RERANKER_PROVIDER degrading
to lexical) would compare `retrieval.floor` against the wrong score
distribution (ADR-0005) with nothing looking broken.

No constructor here opens a socket or loads a model. That lets main.py build
the graph at import time without the DB or vLLM.

`build_providers` stays a flat composition root; only `_vllm` and
`_build_cloud_llm` are extracted, each for the reason in its docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.core.config import settings
from ai_engine.core.db.client import SqlAlchemySessionSource
from ai_engine.core.providers.llm.client import LLMClient
from ai_engine.core.providers.llm.models import (
    AnthropicLLM,
    GeminiLLM,
    OpenAILLM,
    VLLMLLM,
)
from ai_engine.core.providers.embeddings import Embedder
from ai_engine.core.providers.llm.local import LexicalClient, StubClient
from ai_engine.core.providers.reranker import Reranker


@dataclass(frozen=True)
class Providers:
    embedder: Embedder
    reranker: Reranker
    llm: LLMClient
    db: SqlAlchemySessionSource


def build_providers() -> Providers:
    match settings.embedding_provider:
        case "stub":
            embedder = Embedder(client=StubClient())
        case "vllm":
            embedder = Embedder(
                client=_vllm(settings.vllm_embed_model, settings.vllm_embed_base_url)
            )
        case other:
            raise ValueError(f"unknown embedding_provider: {other!r} (expected 'vllm' or 'stub')")

    match settings.reranker_provider:
        case "lexical":
            reranker = Reranker(client=LexicalClient())
        case "vllm":
            reranker = Reranker(
                client=_vllm(settings.reranker_model, settings.vllm_rerank_base_url)
            )
        case other:
            raise ValueError(f"unknown reranker_provider: {other!r} (expected 'vllm' or 'lexical')")

    # --- LLM chain (spec §10.3, ADR-0007) ---------------------------------
    # Resolved once, here. Cloud is primary when configured, with self-hosted
    # vLLM as its fallback; otherwise vLLM is the only link (ADR-0009).
    self_host = _vllm(settings.vllm_chat_model, settings.vllm_chat_base_url)

    return Providers(
        embedder=embedder,
        reranker=reranker,
        llm=_build_cloud_llm(fallback=self_host) or self_host,
        db=SqlAlchemySessionSource(),
    )


def _vllm(model: str, base_url: str) -> VLLMLLM:
    """A client for one vLLM server — one model per server (ADR-0009). Never a
    fallback: embed and rerank must not switch model mid-run (ADR-0005)."""

    return VLLMLLM(
        model=model,
        base_url=base_url,
        connect_timeout=settings.model_connect_timeout_sec,
        read_timeout=settings.model_timeout_sec,
        fallback=None,
    )


def _build_cloud_llm(*, fallback: LLMClient) -> LLMClient | None:
    """Pick the cloud link from config, or None for self-hosted only.

    `cloud_api_key` enables the cloud primary; `cloud_provider` picks the
    protocol. Every half-configured shape is fatal: a cloud link the
    operator believes is active but silently isn't is the same failure as
    a typo'd RERANKER_PROVIDER.
    """

    api_key = settings.cloud_api_key
    base_url = settings.cloud_base_url

    if not api_key:
        if base_url:
            raise ValueError(
                "cloud provider half-configured: CLOUD_BASE_URL is set but CLOUD_API_KEY "
                "is unset. Set both to enable the cloud primary, or neither to run "
                "self-hosted only."
            )
        return None

    match settings.cloud_provider:
        case "openai":
            if not base_url:
                raise ValueError(
                    "cloud_provider='openai' requires CLOUD_BASE_URL (the "
                    "OpenAI-compatible endpoint). Use cloud_provider='anthropic' or "
                    "'gemini' to call a first-party API instead."
                )
            return OpenAILLM(
                model=settings.cloud_model,
                base_url=base_url,
                api_key=api_key,
                connect_timeout=settings.model_connect_timeout_sec,
                fallback=fallback,
            )
        case "anthropic":
            return AnthropicLLM(
                model=settings.cloud_model,
                api_key=api_key,
                max_output_tokens=settings.cloud_max_output_tokens,
                base_url=base_url,
                fallback=fallback,
            )
        case "gemini":
            if base_url:
                raise ValueError(
                    "cloud_provider='gemini' does not support CLOUD_BASE_URL — the "
                    "Google client has no endpoint override. Unset it, or use "
                    "cloud_provider='openai' to reach Gemini through a compatible "
                    "gateway."
                )
            return GeminiLLM(
                model=settings.cloud_model,
                api_key=api_key,
                max_output_tokens=settings.cloud_max_output_tokens,
                fallback=fallback,
            )
        case other:
            raise ValueError(
                f"unknown cloud_provider: {other!r} (expected 'openai', 'anthropic' or 'gemini')"
            )
