"""
The single place provider selection happens.

Previously `embed_text` and `rerank` each re-read a settings string on every
call and fell through silently on anything unrecognized. That made a typo'd
`RERANKER_PROVIDER` degrade to the lexical scorer, whose score distribution
is a different calibration from the cross-encoder one `retrieval.floor` was
fitted against (ADR-0005) — so the refuse-before-LLM rate would be wrong and
nothing would look broken. Selection now happens once, at startup, and an
unknown value is fatal.

Every constructor called here is pure: no socket, no file read, no model
download. That is what keeps `build_graph()` callable at uvicorn import time
and in a test with no database and no environment.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.config import Settings
from ai_engine.db import PsycopgConnectionSource
from ai_engine.llm.client import DefaultLLMClient
from ai_engine.providers.embeddings import OllamaEmbedder, StubEmbedder
from ai_engine.providers.protocols import ConnectionSource, Embedder, LLMClient, Reranker
from ai_engine.providers.reranker import CrossEncoderReranker, LexicalReranker


@dataclass(frozen=True)
class Providers:
    embedder: Embedder
    reranker: Reranker
    llm: LLMClient
    db: ConnectionSource


def build_providers(s: Settings) -> Providers:
    match s.embedding_provider:
        case "stub":
            embedder: Embedder = StubEmbedder()
        case "ollama":
            embedder = OllamaEmbedder(
                base_url=s.ollama_base_url,
                model=s.ollama_embed_model,
                timeout_sec=s.model_timeout_sec,
                connect_timeout_sec=s.model_connect_timeout_sec,
            )
        case other:
            raise ValueError(f"unknown embedding_provider: {other!r} (expected 'ollama' or 'stub')")

    match s.reranker_provider:
        case "lexical":
            reranker: Reranker = LexicalReranker()
        case "cross_encoder":
            reranker = CrossEncoderReranker(model_name=s.reranker_model)
        case other:
            raise ValueError(
                f"unknown reranker_provider: {other!r} (expected 'lexical' or 'cross_encoder')"
            )

    return Providers(
        embedder=embedder,
        reranker=reranker,
        llm=DefaultLLMClient(),
        db=PsycopgConnectionSource(database_url=s.database_url),
    )
