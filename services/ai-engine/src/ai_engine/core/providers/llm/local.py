"""
Clients that need no model server, for CI and offline work. They exercise the
pipeline's shape, not retrieval quality.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

import numpy as np

from ai_engine.core.providers.llm.client import LLMClient

# Must match EMBED_DIM in providers/embeddings.py, which checks it; kept local
# so this module does not import the class that consumes it.
_STUB_DIM = 1024


class StubClient(LLMClient):
    """Deterministic sha256-seeded unit vectors. Serves `embed` only.
    Stateless."""

    def __init__(self) -> None:
        super().__init__(model_name="stub", cost_per_1k_tokens=0.0, fallback=None)

    def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=_STUB_DIM)
        vec = vec / np.linalg.norm(vec)
        return vec.tolist()


class LexicalClient(LLMClient):
    """Token-overlap scoring, |query ∩ passage| / |query|. Serves `rerank`
    only.

    NOT a stand-in for retrieval quality, and its scores cannot be compared
    against `retrieval.floor` (ADR-0005). Stateless.
    """

    def __init__(self) -> None:
        super().__init__(model_name="lexical", cost_per_1k_tokens=0.0, fallback=None)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        return [self._lexical_score(query, p) for p in passages]

    @staticmethod
    def _strip_diacritics(text: str) -> str:
        # `đ` is a distinct letter, not d + a combining mark, so NFD alone
        # leaves it in place and unaccented tickets never match.
        text = text.replace("đ", "d").replace("Đ", "D")
        decomposed = unicodedata.normalize("NFD", text)
        return "".join(c for c in decomposed if not unicodedata.combining(c))

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens: set[str] = set()
        for raw_token in re.findall(r"\w+", text, re.UNICODE):
            folded = LexicalClient._strip_diacritics(raw_token)
            tokens.add(folded.lower())
        return tokens

    @staticmethod
    def _lexical_score(query: str, passage: str) -> float:
        q, p = LexicalClient._tokenize(query), LexicalClient._tokenize(passage)
        if not q:
            return 0.0
        overlap = len(q & p)
        return overlap / len(q)
