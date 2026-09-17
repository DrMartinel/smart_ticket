"""
Embedding providers. core-api embeds tickets separately
(apps/tickets/services/embeddings.py); the two services never import each
other's code (ADR-0004), so they must be kept on the same model by config.
"""

from __future__ import annotations

import hashlib

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


class VLLMEmbedder(Embedder):
    """bge-m3 on a self-hosted vLLM server, over its OpenAI-compatible
    `/v1/embeddings` (ADR-0009). Nodes never see a LangChain type: `embed`
    returns `list[float]` and RAISES rather than degrading — a zero or empty
    vector would read as "the KB has nothing relevant". Opens no socket at
    construction, since build_providers() runs at import time when vLLM may be
    down. Stateless afterwards.
    """

    def __init__(self) -> None:
        import httpx2
        from langchain_openai import OpenAIEmbeddings

        self._model = settings.vllm_embed_model
        self._embeddings = OpenAIEmbeddings(
            model=self._model,
            base_url=settings.vllm_embed_base_url,
            api_key="EMPTY",
            # Otherwise langchain pre-tokenises with tiktoken and sends token
            # ids from OpenAI's vocabulary, which bge-m3 would embed as garbage.
            check_embedding_ctx_length=False,
            max_retries=0,
            # `openai` vendors httpx2; see VLLMLLM. Separate connect and read
            # timeouts: an unreachable server is knowable in seconds, a cold
            # model load takes 15-20s. Collapsing them is the "submit hangs
            # ~120s" bug.
            timeout=httpx2.Timeout(
                settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
            ),
        )

    def embed(self, text: str) -> list[float]:
        embedding = self._embeddings.embed_query(text)
        if len(embedding) != EMBED_DIM:
            raise ValueError(
                f"embedding model {self._model!r} returned dim {len(embedding)}, "
                f"expected {EMBED_DIM}"
            )
        return embedding
