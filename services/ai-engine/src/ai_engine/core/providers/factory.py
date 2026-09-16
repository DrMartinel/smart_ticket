"""
The single place provider selection happens.

Previously `embed_text` and `rerank` each re-read a settings string on every
call and fell through silently on anything unrecognized. That made a typo'd
`RERANKER_PROVIDER` degrade to the lexical scorer, whose score distribution
is a different calibration from the cross-encoder one `retrieval.floor` was
fitted against (ADR-0005) — so the refuse-before-LLM rate would be wrong and
nothing would look broken. Selection now happens once, at startup, and an
unknown value is fatal.

Every constructor called here is pure — no socket, no file read, no model
download — with ONE deliberate exception: `_load_cross_encoder` below, which
reads ~2.3GB of weights at startup so that no ticket pays the load.
Everything else stays pure, which is what lets main.py build the graph at
uvicorn import time and lets the default configuration be constructed in a
test with no database and no environment.

`build_providers` is written as one flat sequence rather than a tree of
`_build_*` helpers. It is a composition root: read every closed with a
`ValueError`, and see the whole startup contract in one pass. The single
extracted function, `_load_cross_encoder`, is extracted for reasons that are
not stylistic — see its docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.core.config import settings
from ai_engine.core.llm.client import DefaultLLMClient
from ai_engine.core.llm.models import (
    AnthropicChatModelFactory,
    ChatModelFactory,
    GeminiChatModelFactory,
    OllamaChatModelFactory,
    OpenAIChatModelFactory,
)
from ai_engine.core.providers.base import ConnectionSource, Embedder, LLMClient, Reranker
from ai_engine.core.providers.db import PsycopgConnectionSource
from ai_engine.core.providers.embeddings import OllamaEmbedder, StubEmbedder
from ai_engine.core.providers.reranker import CrossEncoderReranker, LexicalReranker


@dataclass(frozen=True)
class Providers:
    embedder: Embedder
    reranker: Reranker
    llm: LLMClient
    db: ConnectionSource


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
    #
    # Every misconfiguration below is fatal rather than a fallback to
    # Ollama-only. A cloud link the operator believes is active but which
    # silently is not has the same shape as a typo'd RERANKER_PROVIDER:
    # nothing looks broken, the service is just quietly doing something else.
    api_key = settings.cloud_api_key
    base_url = settings.cloud_base_url

    cloud: ChatModelFactory | None
    if not api_key:
        if base_url:
            raise ValueError(
                "cloud provider half-configured: CLOUD_BASE_URL is set but CLOUD_API_KEY "
                "is unset. Set both to enable the cloud primary, or neither to run "
                "Ollama-only."
            )
        cloud = None
    else:
        match settings.cloud_provider:
            case "openai":
                if not base_url:
                    raise ValueError(
                        "cloud_provider='openai' requires CLOUD_BASE_URL (the "
                        "OpenAI-compatible endpoint). Use cloud_provider='anthropic' or "
                        "'gemini' to call a first-party API instead."
                    )
                cloud = OpenAIChatModelFactory(
                    model=settings.cloud_model,
                    base_url=base_url,
                    api_key=api_key,
                    connect_timeout=settings.model_connect_timeout_sec,
                )
            case "anthropic":
                cloud = AnthropicChatModelFactory(
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
                cloud = GeminiChatModelFactory(
                    model=settings.cloud_model,
                    api_key=api_key,
                    max_output_tokens=settings.cloud_max_output_tokens,
                )
            case other:
                raise ValueError(
                    f"unknown cloud_provider: {other!r} "
                    "(expected 'openai', 'anthropic' or 'gemini')"
                )

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
        db=PsycopgConnectionSource(),
    )


def _load_cross_encoder():
    """Import sentence-transformers and build the model — the one impure
    constructor-time operation in this factory, and the reason it is a named
    module-level function rather than inline code.

    The import is function-local and MUST STAY THAT WAY. This module is
    imported unconditionally by main.py, so hoisting it makes every boot and
    every test session pay ~3.8s of torch import — including under the default
    `RERANKER_PROVIDER=lexical`, which never touches it. Measured: `import
    ai_engine.main` goes from 1.3s to 5.0s.

    Being a module-level name is the other half. Tests reach this through
    `build_providers()`, which takes no arguments, so patching this name is the
    only way to construct a cross-encoder without 2.3GB of real weights; the
    autouse fixture in `services/ai-engine/tests/conftest.py` does exactly
    that. Inline the body and the unit suite goes from 12.3s to 74.1s.

    `revision` is pinned so an upstream commit cannot swap the checkpoint — and
    with it the score distribution `retrieval.floor` was written against —
    without failing loudly (ADR-0005).
    """

    from sentence_transformers import CrossEncoder  # deferred: see above

    return CrossEncoder(settings.reranker_model, revision=settings.reranker_revision)
