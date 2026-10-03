"""
The shortlister (spec §6.3), CandidatePoolNode's scorer:
`CrossEncoderShortlister` (or `LexicalShortlister` offline). Its score orders
the pool so the top `rerank_pool` chunks can be cut for the reranker (Jev),
and is never compared with a threshold (ADR-0005, ADR-0015).
`clients.rerank` owns the `/rerank` request and reply.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod

from ai_engine.core.config import settings
from ai_engine.core.providers import clients


class Shortlister(ABC):
    """What the candidate-pool node depends on: it orders the pool and so
    picks the reranker's shortlist."""

    @abstractmethod
    def score(self, query: str, passages: list[str]) -> list[float]:
        """One score per passage, in input order. Ordering and truncation
        belong to the rerank node."""


class CrossEncoderShortlister(Shortlister):
    """Scores query/passage pairs with `settings.reranker_model` through
    `clients.rerank` (vLLM's `/rerank`). No fallback: another scorer would order the pool, and so
    pick Jev's shortlist, differently. Stateless.
    """

    def score(self, query: str, passages: list[str]) -> list[float]:
        return clients.rerank.rerank(query, passages)


class LexicalShortlister(Shortlister):
    """Deterministic, dependency-free token-overlap scoring,
    |query ∩ passage| / |query|, for offline work. Talks to no server.

    NOT a stand-in for retrieval quality. Stateless.
    """

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = self._tokenize(query)
        if not q:
            return [0.0] * len(passages)
        return [len(q & self._tokenize(p)) / len(q) for p in passages]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Lowercased words with diacritics folded, so a ticket typed without
        tone marks matches an accented KB."""
        # `đ` is a distinct letter, not d + a combining mark, so NFD alone
        # leaves it in place and unaccented tickets never match.
        text = text.replace("đ", "d").replace("Đ", "D")
        decomposed = unicodedata.normalize("NFD", text)
        folded = "".join(c for c in decomposed if not unicodedata.combining(c))
        return {t.lower() for t in re.findall(r"\w+", folded)}


# --- The shortlister, selected once when this module is imported (no I/O) ----
# An unknown provider is fatal here, at boot: falling back to lexical would
# order the pool, and so pick Jev's shortlist, by token overlap with nothing
# looking broken.

shortlister: Shortlister
match settings.shortlist_provider:
    case "lexical":
        shortlister = LexicalShortlister()
    case "vllm":
        shortlister = CrossEncoderShortlister()
    case other:
        raise ValueError(f"unknown shortlist_provider: {other!r} (expected 'vllm' or 'lexical')")
