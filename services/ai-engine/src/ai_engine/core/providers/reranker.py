"""
The `Reranker` implementations (spec §6.3), selected in
`providers/factory.py`.

Their scores are separate calibrations: `retrieval.floor` is a cross-encoder
number (ADR-0005), so under lexical it is silently compared against
token-overlap ratios.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx

from ai_engine.core.config import settings
from ai_engine.core.providers.base import Reranker


class LexicalReranker(Reranker):
    """Deterministic, dependency-free token-overlap scoring, for offline work
    without model weights.

    NOT a stand-in for retrieval quality, and its scores cannot be
    compared against `retrieval.floor` (ADR-0005). Stateless.
    """

    def score(self, query: str, passages: list[str]) -> list[float]:
        return [self._lexical_score(query, p) for p in passages]

    @staticmethod
    def _strip_diacritics(text: str) -> str:
        text = text.replace("đ", "d").replace("Đ", "D")
        decomposed = unicodedata.normalize("NFD", text)
        return "".join(c for c in decomposed if not unicodedata.combining(c))

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens: set[str] = set()
        for raw_token in re.findall(r"\w+", text, re.UNICODE):
            folded = LexicalReranker._strip_diacritics(raw_token)
            tokens.add(folded.lower())
        return tokens

    @staticmethod
    def _lexical_score(query: str, passage: str) -> float:
        q, p = LexicalReranker._tokenize(query), LexicalReranker._tokenize(passage)
        if not q:
            return 0.0
        overlap = len(q & p)
        return overlap / len(q)


class VLLMReranker(Reranker):
    """`reranker_model` served by a self-hosted vLLM server, over its
    Cohere-style `/v1/rerank` (ADR-0009).

    `retrieval.floor` was specified as bge-reranker-v2-m3's sigmoid-normalized
    score (FlagEmbedding's `compute_score(normalize=True)`), never fitted.
    Confirm vLLM returns that same scale before calibrating against it
    (ADR-0005, docs/TODO.md item 4).

    RAISES on any failure or unusable reply; there is no fallback, because
    lexical is a different calibration. The HTTP client opens no socket at
    construction. Read-only afterwards.
    """

    def __init__(self) -> None:
        self._model = settings.reranker_model
        self._client = httpx.Client(
            base_url=settings.vllm_rerank_base_url,
            # Connect and read stay separate: an unreachable server is
            # knowable in seconds, a cold model load is not.
            timeout=httpx.Timeout(
                settings.model_timeout_sec, connect=settings.model_connect_timeout_sec
            ),
        )

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []

        response = self._client.post(
            "/rerank", json={"model": self._model, "query": query, "documents": passages}
        )
        response.raise_for_status()
        return _scores_in_input_order(response.json(), expected=len(passages))


def _scores_in_input_order(body: Any, *, expected: int) -> list[float]:
    """vLLM returns results sorted by score, each carrying its input `index`.
    The rerank node zips scores against its candidates POSITIONALLY, so a
    missing, duplicated or out-of-range index must raise rather than attach a
    score to the wrong chunk."""

    try:
        results = body["results"]
        by_index = {int(r["index"]): float(r["relevance_score"]) for r in results}
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"unusable vLLM rerank reply: {body!r}") from e
    if len(results) != expected or sorted(by_index) != list(range(expected)):
        raise ValueError(
            f"vLLM rerank returned indices {sorted(by_index)}, expected 0..{expected - 1}"
        )
    return [by_index[i] for i in range(expected)]
