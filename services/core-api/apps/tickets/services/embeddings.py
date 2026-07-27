"""
Embedding provider — pluggable, local-first (see plan: "Local-first,
pluggable"). Default is `bge-m3` served by Ollama (1024-dim, multilingual
VI/EN, matching `vector(1024)` throughout the schema). `EMBEDDING_PROVIDER
=stub` swaps in a deterministic hash-based embedder with zero network
dependency, used in CI and any environment without a GPU/Ollama.

core-api needs its own embedder (not just ai-engine's) for: KB ingestion
(kb/services.py), ticket embeddings for incident/duplicate detection
(services/incident.py), and few-shot pool embeddings.
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


def _ollama_embed(text: str) -> list[float]:
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
    resp = httpx.post(
        url, json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text}, timeout=30.0
    )
    resp.raise_for_status()
    embedding = resp.json()["embedding"]
    if len(embedding) != EMBED_DIM:
        raise ValueError(
            f"embedding model {settings.OLLAMA_EMBED_MODEL!r} returned dim "
            f"{len(embedding)}, expected {EMBED_DIM} — check OLLAMA_EMBED_MODEL"
        )
    return embedding


def embed_text(text: str) -> list[float]:
    provider = getattr(settings, "EMBEDDING_PROVIDER", "ollama")
    if provider == "stub":
        return _stub_embed(text)
    return _ollama_embed(text)
