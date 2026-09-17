"""
The two `Reranker` implementations (spec §6.3), selected in
`providers/factory.py`.

Their scores are separate calibrations: `retrieval.floor` is a cross-encoder
number (ADR-0005), so under lexical it is silently compared against
token-overlap ratios.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

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


class CrossEncoderReranker(Reranker):
    """bge-reranker-v2-m3 via FlagEmbedding's `FlagReranker` — spec §6.3.

    Takes an ALREADY-LOADED model and does no I/O; the load happens at
    startup in `providers/factory.py::_load_cross_encoder`. Boot therefore
    blocks until the weights are resident, and an unusable model cache
    kills the container instead of degrading tickets — there is no correct
    fallback, since lexical is a different calibration (ADR-0005).

    No lazy load and no lock: receiving a built model makes a cold-start
    stampede (one multi-GB model per thread, an OOM kill) impossible.
    Reintroduce lazy loading and the lock must come back. Read-only after
    construction.
    """

    def __init__(self, *, model: Any) -> None:
        self._model = model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []

        scores = self._model.compute_score([(query, p) for p in passages], normalize=True)
        return [float(s) for s in scores]
