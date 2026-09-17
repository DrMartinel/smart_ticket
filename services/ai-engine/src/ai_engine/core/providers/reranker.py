"""
Rerankers (spec §6.3). `CrossEncoderReranker` owns the task: it builds the rerank request,
parses the reply and returns one score per passage in input order.
`models.rerank`, built from config at import time, only carries the
request to the model server.

Their scores are separate calibrations: `retrieval.floor` is a cross-encoder
number (ADR-0005), so under `LexicalReranker` it is silently compared against
token-overlap ratios.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ai_engine.core.config import settings
from ai_engine.core.providers.llm import models


class CrossEncoderReranker:
    """Scores query/passage pairs with `settings.reranker_model` through
    `models.rerank`, against a Cohere-style `/rerank` endpoint (as
    vLLM serves). No fallback: another scorer is a different calibration
    (ADR-0005). Stateless.

    `retrieval.floor` was specified as bge-reranker-v2-m3's sigmoid-normalized
    score, never fitted; confirm the server returns that scale before
    calibrating (docs/TODO.md item 4).
    """

    def score(self, query: str, passages: list[str]) -> list[float]:
        """One score per passage, in input order. Ordering and truncation
        belong to the rerank node.

        Per ADR-0005 this is the ONLY number a retrieval threshold is
        compared against — never the rank-derived RRF score.
        """

        if not passages:
            return []
        body = models.rerank.request(
            "/rerank",
            {"model": settings.reranker_model, "query": query, "documents": passages},
        )
        return _scores_in_input_order(body, expected=len(passages))


def _scores_in_input_order(body: Any, *, expected: int) -> list[float]:
    """The server returns results sorted by score, each carrying its input
    `index`. The rerank node zips scores against its candidates POSITIONALLY,
    so a missing, duplicated or out-of-range index raises rather than
    attaching a score to the wrong chunk."""

    try:
        results = body["results"]
        by_index = {int(r["index"]): float(r["relevance_score"]) for r in results}
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"unusable rerank reply: {body!r}") from e
    if len(results) != expected or sorted(by_index) != list(range(expected)):
        raise ValueError(f"rerank returned indices {sorted(by_index)}, expected 0..{expected - 1}")
    return [by_index[i] for i in range(expected)]


class LexicalReranker:
    """Deterministic, dependency-free token-overlap scoring,
    |query ∩ passage| / |query|, for offline work. Talks to no server.

    NOT a stand-in for retrieval quality, and its scores cannot be compared
    against `retrieval.floor` (ADR-0005). Stateless.
    """

    def score(self, query: str, passages: list[str]) -> list[float]:
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
        return {LexicalReranker._strip_diacritics(t).lower() for t in re.findall(r"\w+", text)}

    @staticmethod
    def _lexical_score(query: str, passage: str) -> float:
        q, p = LexicalReranker._tokenize(query), LexicalReranker._tokenize(passage)
        return len(q & p) / len(q) if q else 0.0


# --- The reranker, selected once when this module is imported ----------------
# An unknown value is fatal here, at boot. Falling back to lexical would compare
# `retrieval.floor` against the wrong score distribution (ADR-0005) with nothing
# looking broken.

match settings.reranker_provider:
    case "lexical":
        reranker = LexicalReranker()
    case "vllm":
        reranker = CrossEncoderReranker()
    case other:
        raise ValueError(f"unknown reranker_provider: {other!r} (expected 'vllm' or 'lexical')")
