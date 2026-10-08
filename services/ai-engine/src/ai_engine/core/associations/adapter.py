"""
LightRAG, wired to ai-engine's own models (ADR-0012, ADR-0018). Only the
extraction half of LightRAG is used: documents in, entities per document
out. Its query engine, summaries and answers are never called or read.

Only LightRAG's default file storages are used (JSON KV, NanoVectorDB,
NetworkX), in a working directory the caller names. Nothing imports
`lightrag.llm.*`: those modules install packages at runtime through
`pipmaster`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc

from ai_engine.core.config import settings
from ai_engine.core.db.tables import EMBED_DIM
from ai_engine.core.providers import clients
from ai_engine.core.providers.embeddings import embedder

# LightRAG names a document's source with this prefix and the article id, so
# every entity can be traced to its article.
FILE_PATH_PREFIX = "kb:"


class ModelCalls:
    """Counts the build's model calls, for the spike check's report. One per
    build; not thread-shared state on the request path."""

    def __init__(self) -> None:
        self.llm = 0


def _messages(
    prompt: str, system_prompt: str | None, history: list[dict[str, Any]] | None
) -> list[BaseMessage]:
    roles: dict[str, Callable[[str], BaseMessage]] = {
        "system": SystemMessage,
        "user": HumanMessage,
        "assistant": AIMessage,
    }
    messages: list[BaseMessage] = [SystemMessage(system_prompt)] if system_prompt else []
    messages += [roles[m["role"]](m["content"]) for m in history or []]
    return [*messages, HumanMessage(prompt)]


def llm_func(chat_model: BaseChatModel, calls: ModelCalls) -> Callable[..., Any]:
    """LightRAG's `llm_model_func`: one call, no retry (ADR-0007). A failure
    raises, and LightRAG marks the document `failed`; the build then stops
    rather than export a graph missing that article."""

    async def complete(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        calls.llm += 1
        response_format = kwargs.get("response_format")
        extra = {"response_format": response_format} if response_format else {}
        reply = await chat_model.ainvoke(
            _messages(prompt, system_prompt, history_messages), **extra
        )
        if not isinstance(reply.content, str) or not reply.content.strip():
            raise ValueError("extraction model returned no text")
        return reply.content

    return complete


async def _embed(texts: list[str], **_: Any) -> np.ndarray:
    """LightRAG's `embedding_func`, through ai-engine's embedder: the same
    model and width as the KB's chunks (EMBED_DIM). It raises on failure,
    never returns zeros."""

    vectors = [await asyncio.to_thread(embedder.embed, text) for text in texts]
    return np.array(vectors, dtype=np.float32)


def make_rag(
    working_dir: Path,
    *,
    guidance: str,
    calls: ModelCalls,
    chat_model: BaseChatModel | None = None,
    embed: Callable[..., Any] = _embed,
) -> LightRAG:
    """A LightRAG over `working_dir`, extracting with `guidance` (the entity
    policy's) in JSON mode. Construction opens no connection; the caller
    awaits `initialize_storages()`."""

    return LightRAG(
        working_dir=str(working_dir),
        # Explicit: LightRAG would otherwise read a WORKSPACE env var and move
        # its files into a subdirectory the next build wouldn't look in.
        workspace="",
        llm_model_func=llm_func(chat_model or clients.extraction_chat_model(), calls),
        embedding_func=EmbeddingFunc(embedding_dim=EMBED_DIM, func=embed),
        llm_model_max_async=settings.lightrag_llm_max_async,
        entity_extract_max_gleaning=settings.lightrag_max_gleaning,
        chunk_token_size=settings.lightrag_chunk_tokens,
        entity_extraction_use_json=True,
        addon_params={"entity_types_guidance": guidance, "language": "English"},
    )
