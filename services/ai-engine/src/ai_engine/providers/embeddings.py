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

from ai_engine.config import settings

EMBED_DIM = 1024


def _stub_embed(text: str) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=EMBED_DIM)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


def _ollama_embed(text: str) -> list[float]:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/embeddings"
    resp = httpx.post(
        url,
        json={"model": settings.ollama_embed_model, "prompt": text},
        timeout=httpx.Timeout(
            settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
        ),
    )
    resp.raise_for_status()
    embedding = resp.json()["embedding"]
    if len(embedding) != EMBED_DIM:
        raise ValueError(
            f"embedding model {settings.ollama_embed_model!r} returned dim "
            f"{len(embedding)}, expected {EMBED_DIM}"
        )
    return embedding


def embed_text(text: str) -> list[float]:
    if settings.embedding_provider == "stub":
        return _stub_embed(text)
    return _ollama_embed(text)
