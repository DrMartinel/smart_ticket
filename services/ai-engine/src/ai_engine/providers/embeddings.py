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

# A property of bge-m3 AND of the pgvector column width — changing it needs
# a migration, so it is not node configuration.
EMBED_DIM = 1024


class StubEmbedder:
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


class OllamaEmbedder:
    """bge-m3 via Ollama. Stateless, so one instance is safe to share across
    FastAPI's threadpool."""

    def embed(self, text: str) -> list[float]:
        model = settings.ollama_embed_model
        # Long read budget, short connect budget: an unreachable provider is
        # knowable in seconds, while a cold model load legitimately takes
        # 15-20s.
        timeout = httpx.Timeout(
            settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
        )
        resp = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=timeout,
        )
        resp.raise_for_status()
        embedding = resp.json()["embedding"]
        if len(embedding) != EMBED_DIM:
            # Raise rather than return a short vector: a dimension mismatch
            # would otherwise surface as a pgvector error deep inside
            # retrieval, or worse, as silently poor recall.
            raise ValueError(
                f"embedding model {model!r} returned dim {len(embedding)}, expected {EMBED_DIM}"
            )
        return embedding
