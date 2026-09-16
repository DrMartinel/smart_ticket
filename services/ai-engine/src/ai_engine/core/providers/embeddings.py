"""
Same pluggable embedding strategy as core-api's
apps/tickets/services/embeddings.py (bge-m3 via Ollama by default, a
deterministic stub for CI/no-GPU environments) — duplicated rather than
shared because ai-engine and core-api deliberately don't import each
other's code (ADR-0004); `contracts` is the only shared package.
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
    """Deterministic sha256-seeded vectors for CI/no-GPU environments.

    NOT a stand-in for retrieval quality — only for exercising the pipeline
    shape without a GPU or a model download. Stateless; safe to share across
    FastAPI's threadpool.
    """

    def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=EMBED_DIM)
        vec = vec / np.linalg.norm(vec)
        return vec.tolist()


class OllamaEmbedder(Embedder):
    """bge-m3 via Ollama, over langchain-ollama's client (ADR-0007).

    LangChain owns the transport only. The `Embedder` seam is unchanged and
    the nodes never see a LangChain type: `embed` still returns a bare
    `list[float]` and still RAISES rather than degrading, per base.py.

    Configuration is read once, here, rather than per call — same reason as
    the LLM chain in providers/factory.py. Unlike the chat models there is no
    per-call timeout to bucket on (`embed` takes none), so the client is built
    once in __init__ and reused.

    Construction opens no socket: `validate_model_on_init` stays at its
    default of False, which matters because build_providers() runs at uvicorn
    import time and Ollama may not be up yet. Stateless afterwards, so one
    instance is safe to share across FastAPI's threadpool.
    """

    def __init__(self) -> None:
        from langchain_ollama import OllamaEmbeddings

        self._model = settings.ollama_embed_model
        self._embeddings = OllamaEmbeddings(
            model=self._model,
            base_url=settings.ollama_base_url,
            # Long read budget, short connect budget: an unreachable provider
            # is knowable in seconds, while a cold model load legitimately
            # takes 15-20s. `ollama` hands this to httpx verbatim, so the
            # split survives — collapsing the two is the documented
            # "submit hangs ~120s" bug.
            client_kwargs={
                "timeout": httpx.Timeout(
                    settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
                )
            },
        )

    def embed(self, text: str) -> list[float]:
        embedding = self._embeddings.embed_query(text)
        if len(embedding) != EMBED_DIM:
            # Raise rather than return a short vector: a dimension mismatch
            # would otherwise surface as a pgvector error deep inside
            # retrieval, or worse, as silently poor recall. Kept on this side
            # of the seam because langchain-ollama has no opinion about the
            # width our pgvector column was migrated to.
            raise ValueError(
                f"embedding model {self._model!r} returned dim {len(embedding)}, "
                f"expected {EMBED_DIM}"
            )
        return embedding
