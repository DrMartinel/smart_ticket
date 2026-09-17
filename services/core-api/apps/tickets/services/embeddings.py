"""
Embedding provider — pluggable, local-first. Default is `bge-m3` served by
self-hosted vLLM (1024-dim, multilingual VI/EN, matching `vector(1024)`
throughout the schema; ADR-0009). `EMBEDDING_PROVIDER=stub` swaps in a
deterministic hash-based embedder with zero network dependency, used in CI and
any environment without a GPU.

core-api needs its own embedder (not just ai-engine's) for: KB ingestion
(kb/services.py), ticket embeddings for incident/duplicate detection
(services/incident.py), and few-shot pool embeddings. It must use the same
model and runtime as ai-engine's query embeddings, or retrieval degrades
silently.
"""

from __future__ import annotations

import hashlib

import httpx
import numpy as np
from django.conf import settings

EMBED_DIM = 1024


def _stub_embed(text: str) -> list[float]:
    """Deterministic, dependency-free embedding: seed a PRNG from a hash
    of the text and draw a unit vector. Not semantically meaningful, but
    stable and fast enough for CI/eval runs that only need *some* vector
    of the right shape to exercise the retrieval pipeline end-to-end."""

    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=EMBED_DIM)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


def _vllm_embed(text: str) -> list[float]:
    """vLLM's OpenAI-compatible `/v1/embeddings`.

    Every failure surfaces as `httpx.HTTPError` or `ValueError` — the two
    types `process_ticket` turns into an `embedding_unavailable` HITL route.
    Anything else would escape the Celery task and leave the ticket stuck at
    status="new", invisible to every queue.
    """

    url = f"{settings.VLLM_EMBED_BASE_URL.rstrip('/')}/embeddings"
    # Short connect budget, long read budget — an unreachable server is
    # knowable in seconds, while a cold model legitimately needs the full
    # read window. See MODEL_CONNECT_TIMEOUT_SEC in settings.
    resp = httpx.post(
        url,
        json={"model": settings.VLLM_EMBED_MODEL, "input": text},
        timeout=httpx.Timeout(
            float(settings.MODEL_TIMEOUT_SEC), connect=float(settings.MODEL_CONNECT_TIMEOUT_SEC)
        ),
    )
    resp.raise_for_status()
    try:
        embedding = resp.json()["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"unexpected embeddings response shape: {resp.text[:200]!r}") from e
    if not isinstance(embedding, list) or len(embedding) != EMBED_DIM:
        raise ValueError(
            f"embedding model {settings.VLLM_EMBED_MODEL!r} returned "
            f"{len(embedding) if isinstance(embedding, list) else type(embedding).__name__}, "
            f"expected {EMBED_DIM} dims — check VLLM_EMBED_MODEL"
        )
    return embedding


def embed_text(text: str) -> list[float]:
    provider = settings.EMBEDDING_PROVIDER
    if provider == "stub":
        return _stub_embed(text)
    if provider == "vllm":
        return _vllm_embed(text)
    # ValueError, so a typo reaches a human as embedding_unavailable rather
    # than quietly picking a provider.
    raise ValueError(f"unknown EMBEDDING_PROVIDER: {provider!r} (expected 'vllm' or 'stub')")
