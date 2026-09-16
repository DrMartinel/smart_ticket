"""
The two `Reranker` implementations (spec §6.3), selected by
`RERANKER_PROVIDER` in `providers/factory.py`. See each class for what it
costs and what it does not buy.

`cross_encoder` is the DEFAULT and the only calibrated one. Their outputs
are separate calibrations and never interchangeable: `retrieval.floor` is
specified against the cross-encoder distribution (ADR-0005), so running
lexical compares that floor against token-overlap ratios — a different
question, answered silently and without error.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ai_engine.core.providers.base import Reranker


class LexicalReranker(Reranker):
    """Deterministic, dependency-free token-overlap scoring. NO LONGER THE
    DEFAULT, and no longer what CI runs — both now use the cross-encoder, so
    that the thresholds under test are the ones production uses.

    Retained as a test double for offline work with no weights available. It
    is NOT a stand-in for retrieval quality: it exercises the pipeline shape,
    and nothing it produces can be compared against `retrieval.floor`, which
    is a cross-encoder number (ADR-0005). Stateless.
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
    """bge-reranker-v2-m3 via sentence-transformers — spec §6.3.

    Takes an ALREADY-LOADED model. It does not import sentence-transformers,
    does not read the model cache, and does no I/O of any kind — the ~5.3s of
    torch import plus weight deserialization happens in
    `providers/factory.py::_load_cross_encoder`, at startup, so no ticket pays
    it. Same shape as every node in this service: collaborators arrive through
    __init__ and the composition root owns the impure part.

    Two consequences of loading at startup, both intended:

    * With `RERANKER_PROVIDER=cross_encoder`, importing `ai_engine.main` blocks
      for the load, so the process looks hung for a few seconds at boot and
      serves no `/healthz` until the weights are resident.
    * An unusable model cache kills the container instead of degrading one
      ticket to HITL. There is no correct fallback: the lexical scorer is a
      different calibration from the one `retrieval.floor` was fitted against
      (ADR-0005), so failing the boot is the loud version.

    There is deliberately NO lock and no lazy load. Both existed to stop a
    cold-start stampede from building one multi-GB model per thread of
    FastAPI's threadpool; receiving a built model makes the race impossible.
    If anyone reintroduces lazy loading, the lock has to come back with it —
    a model built per racing request is an OOM kill, not a slow request.

    Read-only after construction, like every other node/provider.
    """

    def __init__(self, *, model: Any) -> None:
        self._model = model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        raw_scores = self._model.predict([(query, p) for p in passages])
        # bge-reranker-v2-m3 outputs an unbounded logit; squash to [0,1] so
        # it composes with the same floor/margin semantics as the lexical
        # fallback. Kept as a literal rather than math.exp: this feeds the
        # exact number `retrieval_floor` is compared against (ADR-0005).
        return [1 / (1 + pow(2.718281828, -float(s))) for s in raw_scores]
