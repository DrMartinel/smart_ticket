"""
The single place provider selection happens — once, at startup, with any
unknown value fatal. A silent fallback (a typo'd RERANKER_PROVIDER degrading
to lexical) would compare `retrieval.floor` against the wrong score
distribution (ADR-0005) with nothing looking broken.

No constructor here opens a socket or reads a file, except
`_load_cross_encoder`, which loads the reranker weights so no ticket pays for
it. That lets main.py build the graph at import time without the DB or Ollama.

`build_providers` stays a flat composition root; only `_build_cloud_factory`
and `_load_cross_encoder` are extracted, each for the reason in its docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.core.config import settings
from ai_engine.core.db.client import SqlAlchemySessionSource
from ai_engine.core.llm.base import LLMClient
from ai_engine.core.llm.client import DefaultLLMClient
from ai_engine.core.llm.models import (
    AnthropicChatModelFactory,
    ChatModelFactory,
    GeminiChatModelFactory,
    OllamaChatModelFactory,
    OpenAIChatModelFactory,
)
from ai_engine.core.providers.base import Embedder, Reranker
from ai_engine.core.providers.embeddings import OllamaEmbedder, StubEmbedder
from ai_engine.core.providers.reranker import CrossEncoderReranker, LexicalReranker


@dataclass(frozen=True)
class Providers:
    embedder: Embedder
    reranker: Reranker
    llm: LLMClient
    db: SqlAlchemySessionSource


def build_providers() -> Providers:
    match settings.embedding_provider:
        case "stub":
            embedder: Embedder = StubEmbedder()
        case "ollama":
            embedder = OllamaEmbedder()
        case other:
            raise ValueError(f"unknown embedding_provider: {other!r} (expected 'ollama' or 'stub')")

    match settings.reranker_provider:
        case "lexical":
            reranker: Reranker = LexicalReranker()
        case "cross_encoder":
            reranker = CrossEncoderReranker(model=_load_cross_encoder())
        case other:
            raise ValueError(
                f"unknown reranker_provider: {other!r} (expected 'lexical' or 'cross_encoder')"
            )

    # --- LLM chain (spec §10.3, ADR-0007) ---------------------------------
    # Resolved once, here, rather than re-derived from `settings` on every
    # call as DefaultLLMClient used to. Cloud is primary when configured, with
    # Ollama behind it; otherwise Ollama is primary and there is no second
    # link.
    cloud = _build_cloud_factory()

    ollama = OllamaChatModelFactory(
        model=settings.ollama_infer_model,
        base_url=settings.ollama_base_url,
        connect_timeout=settings.model_connect_timeout_sec,
    )

    return Providers(
        embedder=embedder,
        reranker=reranker,
        llm=DefaultLLMClient(
            primary=cloud or ollama,
            fallback=ollama if cloud else None,
            default_timeout=settings.model_timeout_sec,
        ),
        db=SqlAlchemySessionSource(),
    )


def _build_cloud_factory() -> ChatModelFactory | None:
    """Pick the cloud link from config, or None for Ollama-only.

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
                "Ollama-only."
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
            return OpenAIChatModelFactory(
                model=settings.cloud_model,
                base_url=base_url,
                api_key=api_key,
                connect_timeout=settings.model_connect_timeout_sec,
            )
        case "anthropic":
            return AnthropicChatModelFactory(
                model=settings.cloud_model,
                api_key=api_key,
                max_output_tokens=settings.cloud_max_output_tokens,
                base_url=base_url,
            )
        case "gemini":
            if base_url:
                raise ValueError(
                    "cloud_provider='gemini' does not support CLOUD_BASE_URL — the "
                    "Google client has no endpoint override. Unset it, or use "
                    "cloud_provider='openai' to reach Gemini through a compatible "
                    "gateway."
                )
            return GeminiChatModelFactory(
                model=settings.cloud_model,
                api_key=api_key,
                max_output_tokens=settings.cloud_max_output_tokens,
            )
        case other:
            raise ValueError(
                f"unknown cloud_provider: {other!r} (expected 'openai', 'anthropic' or 'gemini')"
            )


def _load_cross_encoder():
    """Load the FlagEmbedding reranker — the one impure constructor in this
    factory.

    The import is function-local and MUST stay so: main.py always imports
    this module, and hoisting it makes every boot and test session pay
    seconds of torch import, even under `lexical`. It is a module-level
    name so tests can patch it (`build_providers()` takes no arguments);
    see the autouse fixture in tests/conftest.py.

    `revision` is pinned so an upstream commit cannot silently swap the
    checkpoint `retrieval.floor` is calibrated against (ADR-0005).
    `FlagReranker` takes no revision, so it is resolved to a local
    snapshot first; under HF_HUB_OFFLINE=1 a revision missing from the
    baked cache raises.
    """

    # deferred: see above
    from FlagEmbedding import FlagReranker
    from huggingface_hub import snapshot_download

    path = snapshot_download(settings.reranker_model, revision=settings.reranker_revision)
    return FlagReranker(path, use_fp16=settings.reranker_use_fp16)
