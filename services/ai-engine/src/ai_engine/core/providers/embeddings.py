"""
Embedding providers, duplicated from core-api's
apps/tickets/services/embeddings.py because the two services never import each
other's code (ADR-0004).
"""

from __future__ import annotations

import hashlib

import httpx
import numpy as np

from ai_engine.core.config import settings
from ai_engine.core.providers.base import Embedder

# A property of bge-m3 AND of the pgvector column width — changing it needs
# a migration, so it is not node configuration.
EMBED_DIM = 1024


class StubEmbedder(Embedder):
    """Deterministic sha256-seeded vectors for CI/no-GPU runs. Exercises the
    pipeline shape, not retrieval quality. Stateless.
    """

    def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=EMBED_DIM)
        vec = vec / np.linalg.norm(vec)
        return vec.tolist()


class OllamaEmbedder(Embedder):
    """bge-m3 via Ollama over langchain-ollama (ADR-0007). Nodes never see a
    LangChain type: `embed` returns `list[float]` and RAISES rather than
    degrading.

    The client is built once in __init__ and opens no socket
    (`validate_model_on_init` stays False), since build_providers() runs
    at import time when Ollama may be down. Stateless afterwards.
    """

    def __init__(self) -> None:
        from langchain_ollama import OllamaEmbeddings

        self._model = settings.ollama_embed_model
        self._embeddings = OllamaEmbeddings(
            model=self._model,
            base_url=settings.ollama_base_url,
            client_kwargs={
                "timeout": httpx.Timeout(
                    settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
                )
            },
        )

    def embed(self, text: str) -> list[float]:
        embedding = self._embeddings.embed_query(text)
        if len(embedding) != EMBED_DIM:
            raise ValueError(
                f"embedding model {self._model!r} returned dim {len(embedding)}, "
                f"expected {EMBED_DIM}"
            )
        return embedding
