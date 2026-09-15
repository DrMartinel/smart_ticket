"""
Cross-encoder reranker — spec §6.3: `bge-reranker-v2-m3` by default,
loaded lazily via sentence-transformers so importing this module never
requires the (large, GPU-friendly but heavy) dependency unless
RERANKER_PROVIDER=cross_encoder is actually selected.

`RERANKER_PROVIDER=lexical` is the deterministic, dependency-free
fallback used in CI and the eval suite — pure token-overlap scoring. It
is NOT a stand-in for retrieval quality, only for exercising the pipeline
shape without a GPU or a model download.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable
from typing import Any

from ai_engine.core.config import settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _strip_diacritics(text: str) -> str:
    """Fold Vietnamese tone/vowel marks: "đăng nhập" -> "dang nhap".

    Vietnamese speakers very often type support tickets without
    diacritics ("khong dang nhap duoc may tinh") while KB articles are
    written with them ("không đăng nhập được máy tính"). To exact token
    matching those are disjoint vocabularies, so a ticket that is nearly
    a verbatim restatement of a KB title scored ~0.04 instead of ~0.75 —
    far below `retrieval.floor`, which triggered refuse-before-LLM and
    sent every such ticket to a human as "nothing in the KB matches".

    NFD splits a base letter from its combining marks so the marks can be
    dropped; đ/Đ are handled separately because they are distinct letters
    rather than a decomposable base + mark.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _tokenize(text: str) -> set[str]:
    return {_strip_diacritics(t).lower() for t in _TOKEN_RE.findall(text)}


def _lexical_score(query: str, passage: str) -> float:
    q, p = _tokenize(query), _tokenize(passage)
    if not q or not p:
        return 0.0
    overlap = len(q & p)
    return overlap / len(q)  # in [0, 1] — fraction of query tokens covered


class LexicalReranker:
    """Deterministic, dependency-free token-overlap scoring — the CI/eval
    fallback. NOT a stand-in for retrieval quality, only for exercising the
    pipeline shape without a GPU or a model download. Stateless."""

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [_lexical_score(query, p) for p in passages]


class CrossEncoderReranker:
    """bge-reranker-v2-m3 via sentence-transformers — spec §6.3.

    `sentence-transformers` is an OPTIONAL extra (`--extra cross-encoder`).
    Constructing this class must never import it and never touch the model
    cache: main.py builds the graph at uvicorn import time, and a default
    (RERANKER_PROVIDER=lexical) install does not have the package at all.
    Hence the function-local import in `_import_and_build_cross_encoder`
    below — do not hoist it; there is a test whose only job is to fail if
    someone does.

    `_model` is the ONE intentionally-mutable attribute in the node/provider
    layer; everything else is read-only after __init__.
    """

    def __init__(self, *, loader: Callable[[str], Any] | None = None) -> None:
        # The `loader` seam exists so laziness and the load lock can be
        # tested WITHOUT sentence-transformers installed. That is its only
        # purpose — it is not a plugin point.
        self._loader = loader or _import_and_build_cross_encoder
        self._model: Any | None = None
        self._load_lock = threading.Lock()

    def _model_or_load(self) -> Any:
        # Double-checked locking. `analyze` in main.py is a sync def, so
        # FastAPI runs it in a threadpool — without the lock, two concurrent
        # first requests each build a CrossEncoder, doubling peak RAM for a
        # multi-GB model while one copy is immediately discarded. The warm
        # path below reads self._model with no lock at all.
        model = self._model
        if model is not None:
            return model
        with self._load_lock:
            if self._model is None:
                self._model = self._loader(settings.reranker_model)
            return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        # The lock is NOT held below this line: holding it across predict()
        # would serialize every rerank in the process, a far worse
        # regression than the duplicate-load it prevents.
        model = self._model_or_load()
        raw_scores = model.predict([(query, p) for p in passages])
        # bge-reranker-v2-m3 outputs an unbounded logit; squash to [0,1] so
        # it composes with the same floor/margin semantics as the lexical
        # fallback. Kept as a literal rather than math.exp: this feeds the
        # exact number `retrieval_floor` is compared against (ADR-0005).
        return [1 / (1 + pow(2.718281828, -float(s))) for s in raw_scores]


def _import_and_build_cross_encoder(model_name: str):
    from sentence_transformers import CrossEncoder  # deferred: optional extra

    return CrossEncoder(model_name)
