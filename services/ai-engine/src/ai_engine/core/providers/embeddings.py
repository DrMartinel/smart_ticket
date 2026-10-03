"""
Embedders (spec §6.3). `LexicalEmbedder` gets its vector from
`clients.embed` (which owns the `/embeddings` request and reply) and checks
it is fit for pgvector.

core-api embeds tickets, KB articles and few-shot examples through
`POST /v1/embed` (ADR-0012), so every vector in the system comes from this
`embedder`, stub included.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import numpy as np
from ai_engine.core.config import settings
from ai_engine.core.db.tables import EMBED_DIM
from ai_engine.core.providers import clients


class Embedder(ABC):
    """What the retrieve and few-shot nodes, and `POST /v1/embed`, depend on."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The model that produces the vectors. core-api stores it with each
        ticket embedding (ADR-0012)."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """One dense vector of EMBED_DIM floats. Raises on provider failure —
        never a zero or empty vector. That would read as "the KB has nothing
        relevant" instead of "the embedder is down", and the two reach HITL
        under different reason codes."""


class LexicalEmbedder(Embedder):
    """Embeds text with `settings.embed_model` through
    `clients.embed`, against an OpenAI-compatible `/embeddings`
    endpoint. Stateless.
    """

    @property
    def model(self) -> str:
        return settings.embed_model

    def embed(self, text: str) -> list[float]:
        vector = clients.embed.embed(text)
        if len(vector) != EMBED_DIM:
            raise ValueError(
                f"{settings.embed_model!r} returned dim {len(vector)}, expected {EMBED_DIM}"
            )
        return vector


class StubEmbedder(Embedder):
    """Deterministic sha256-seeded unit vectors for CI/no-GPU runs. Talks to
    no server. Exercises the pipeline shape, not retrieval quality.
    Stateless."""

    @property
    def model(self) -> str:
        return "stub"

    def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=EMBED_DIM)
        vec = vec / np.linalg.norm(vec)
        return vec.tolist()


# --- The embedder, selected once when this module is imported ----------------
# An unknown value is fatal here, at boot: silently embedding with the wrong
# provider produces plausible-looking vectors and quietly bad recall.

embedder: Embedder
match settings.embedding_provider:
    case "stub":
        embedder = StubEmbedder()
    case "vllm":
        embedder = LexicalEmbedder()
    case other:
        raise ValueError(f"unknown embedding_provider: {other!r} (expected 'vllm' or 'stub')")
