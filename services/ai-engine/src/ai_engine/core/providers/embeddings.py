"""
The embedder nodes depend on. It owns the contract, not the model: the
injected `LLMClient` computes the vector, and this class checks it is fit for
pgvector.

core-api embeds tickets separately (apps/tickets/services/embeddings.py); the
two services never import each other's code (ADR-0004), so they must be kept on
the same model by config.
"""

from __future__ import annotations

from ai_engine.core.providers.llm.client import LLMClient

# A property of bge-m3 AND of the pgvector column width — changing it needs
# a migration, so it is not node configuration.
EMBED_DIM = 1024


class Embedder:
    """Embeds text through any `LLMClient` that serves embeddings.

    Raises at construction if the client does not, so a misconfigured
    provider fails the boot rather than the first ticket. Read-only after
    construction.
    """

    def __init__(self, *, client: LLMClient) -> None:
        if not client.supports("embed"):
            raise TypeError(f"{type(client).__name__} does not serve embeddings")
        self._client = client

    def embed(self, text: str) -> list[float]:
        """One dense vector of EMBED_DIM floats.

        Raises on provider failure — never a zero or empty vector. That would
        read as "the KB has nothing relevant" instead of "the embedder is
        down", and the two reach HITL under different reason codes.
        """

        vector = self._client.embed(text)
        # EMBED_DIM is the pgvector column width, which no client knows about.
        # A wrong-width vector would fail far away as a pgvector error, or —
        # if empty — as an ordinary refuse-before-LLM.
        if len(vector) != EMBED_DIM:
            raise ValueError(
                f"{self._client.model_name!r} returned dim {len(vector)}, expected {EMBED_DIM}"
            )
        return vector
