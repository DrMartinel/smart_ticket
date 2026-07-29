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
import unicodedata
from functools import lru_cache

from ai_engine.config import settings

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


@lru_cache(maxsize=1)
def _cross_encoder_model():
    from sentence_transformers import CrossEncoder

    return CrossEncoder("BAAI/bge-reranker-v2-m3")


def rerank(query: str, passages: list[str]) -> list[float]:
    """Returns one score per passage, same order as input. Scores are
    calibrated relevance judgments (cross-encoder) or a rough proxy
    (lexical) — either way, ADR-0005 applies: this is the ONLY score a
    retrieval threshold is ever compared against, never the RRF score."""

    if not passages:
        return []

    if settings.reranker_provider == "cross_encoder":
        model = _cross_encoder_model()
        pairs = [(query, p) for p in passages]
        raw_scores = model.predict(pairs)
        # bge-reranker-v2-m3 outputs an unbounded logit; squash to [0,1]
        # so it composes with the same floor/margin semantics as the
        # lexical fallback.
        return [1 / (1 + pow(2.718281828, -float(s))) for s in raw_scores]

    return [_lexical_score(query, p) for p in passages]
