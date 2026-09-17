"""
Embedders (spec §6.3). `LexicalEmbedder` owns the task: it builds the embeddings
request, parses the reply and checks the vector is fit for pgvector.
`models.embed`, built from config at import time, only carries the
request to the model server.

core-api embeds tickets separately (apps/tickets/services/embeddings.py); the
two services never import each other's code (ADR-0004), so they must be kept on
the same model by config.
"""

from __future__ import annotations

import hashlib

import numpy as np

from ai_engine.core.config import settings
from ai_engine.core.providers.llm import models

# A property of bge-m3 AND of the pgvector column width — changing it needs
# a migration, so it is not node configuration.
EMBED_DIM = 1024


class LexicalEmbedder:
    """Embeds text with `settings.embed_model` through
    `models.embed`, against an OpenAI-compatible `/embeddings`
    endpoint. Stateless.
    """

    def embed(self, text: str) -> list[float]:
        """One dense vector of EMBED_DIM floats.

        Raises on provider failure — never a zero or empty vector. That would
        read as "the KB has nothing relevant" instead of "the embedder is
        down", and the two reach HITL under different reason codes.
        """

        model = settings.embed_model
        body = models.embed.request("/embeddings", {"model": model, "input": text})
        try:
            vector = body["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"unusable embeddings reply: {body!r}") from e
        if not isinstance(vector, list) or len(vector) != EMBED_DIM:
            size = len(vector) if isinstance(vector, list) else type(vector).__name__
            raise ValueError(f"{model!r} returned dim {size}, expected {EMBED_DIM}")
        return vector


class StubEmbedder:
    """Deterministic sha256-seeded unit vectors for CI/no-GPU runs. Talks to
    no server. Exercises the pipeline shape, not retrieval quality.
    Stateless."""

    def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=EMBED_DIM)
        vec = vec / np.linalg.norm(vec)
        return vec.tolist()


# --- The embedder, selected once when this module is imported ----------------
# An unknown value is fatal here, at boot: silently embedding with the wrong
# provider produces plausible-looking vectors and quietly bad recall.

match settings.embedding_provider:
    case "stub":
        embedder = StubEmbedder()
    case "vllm":
        embedder = LexicalEmbedder()
    case other:
        raise ValueError(f"unknown embedding_provider: {other!r} (expected 'vllm' or 'stub')")
