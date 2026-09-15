"""
Reciprocal Rank Fusion — spec §6.3.

    score(d) = Σ 1 / (k + rank_i(d))

k=60 is the standard constant from the original RRF paper and is not
meant to be tuned (spec §13 comment). The output of this module is an
ORDERED LIST of candidates, not a scored one that anything downstream
should threshold against — see ADR-0005. `Candidate.rrf_score` exists
only to make the sort itself inspectable in tests/logs; nothing outside
this module should read it as a relevance signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.core.config import settings
from ai_engine.retrieval.bm25 import LexicalHit
from ai_engine.retrieval.vector import VectorHit


@dataclass(frozen=True)
class Candidate:
    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    rrf_score: float  # ranking aid only — see module docstring / ADR-0005


def reciprocal_rank_fusion(
    bm25_hits: list[LexicalHit], vector_hits: list[VectorHit]
) -> list[Candidate]:
    k = settings.rrf_k
    scores: dict[int, float] = {}
    meta: dict[int, tuple[int, str, str]] = {}

    for rank, hit in enumerate(bm25_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        meta[hit.chunk_id] = (hit.article_id, hit.article_slug, hit.content)

    for rank, hit in enumerate(vector_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        meta[hit.chunk_id] = (hit.article_id, hit.article_slug, hit.content)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        Candidate(
            chunk_id=chunk_id,
            article_id=meta[chunk_id][0],
            article_slug=meta[chunk_id][1],
            content=meta[chunk_id][2],
            rrf_score=score,
        )
        for chunk_id, score in ordered
    ]
