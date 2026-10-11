"""
Reciprocal Rank Fusion — spec §6.3.

    score(d) = w / (k + rank_bm25(d)) + 1 / (k + rank_vector(d))

k=60 is the standard constant from the RRF paper, not meant to be tuned.
w is BM25's vote (`rrf_bm25_weight`). A ticket describes symptoms in its own
words, which keyword matching finds less often than the embedding does.
Once w / (k + 1) < 1 / (k + vector_top_k) (w < 0.76 at k=60 and top k 20), a
chunk only BM25 found can't outrank one vector search found, so BM25 only
reorders the chunks both lists agree on. The
output is an ORDERED list only: the fused score sorts and is deliberately not
carried on `Candidate`, so nothing can threshold against it (ADR-0005).
"""

from __future__ import annotations

import uuid

from ai_engine.core.config import settings
from ai_engine.graph.state import Candidate
from ai_engine.graph.nodes.retrieve.bm25 import LexicalHit
from ai_engine.graph.nodes.retrieve.vector import VectorHit


def reciprocal_rank_fusion(
    bm25_hits: list[LexicalHit], vector_hits: list[VectorHit]
) -> list[Candidate]:
    k = settings.rrf_k
    w = settings.rrf_bm25_weight
    scores: dict[uuid.UUID, float] = {}
    meta: dict[uuid.UUID, tuple[uuid.UUID, str, str]] = {}

    for rank, hit in enumerate(bm25_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + w / (k + rank)
        meta[hit.chunk_id] = (hit.article_id, hit.article_slug, hit.content)

    for rank, vhit in enumerate(vector_hits, start=1):
        scores[vhit.chunk_id] = scores.get(vhit.chunk_id, 0.0) + 1.0 / (k + rank)
        meta[vhit.chunk_id] = (vhit.article_id, vhit.article_slug, vhit.content)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        Candidate(
            chunk_id=chunk_id,
            article_id=meta[chunk_id][0],
            article_slug=meta[chunk_id][1],
            content=meta[chunk_id][2],
        )
        for chunk_id, _ in ordered
    ]
