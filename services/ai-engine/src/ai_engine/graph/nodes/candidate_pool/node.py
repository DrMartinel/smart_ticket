"""
Candidate pool — the cross-encoder pass, and link expansion (ADR-0014
decisions 1-2, ADR-0015). The cross-encoder scores the fused candidates; the
articles of its top `link_expansion_seeds` chunks are the seeds; the pages
they link to add their chunks nearest the ticket; the cross-encoder scores
those too. The pool leaves in cross-encoder order, for RerankNode to cut to
Jev's shortlist and re-score.

Every score here is the cross-encoder's. Seeds come from its order, never
from RRF's (ADR-0005).
"""

from __future__ import annotations

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode, StateUpdate
from ai_engine.graph.nodes.candidate_pool.shortlister import shortlister
from ai_engine.graph.state import Candidate
from ai_engine.graph.nodes.candidate_pool.links import linked_article_ids, nearest_chunks
from ai_engine.graph.state import RankedChunk, TriageState


def _scored(query: str, candidates: list[Candidate]) -> list[RankedChunk]:
    """The candidates with their cross-encoder scores, in input order. A
    shortlister failure raises: the pool is never silently smaller."""

    scores = shortlister.score(query, [c.content for c in candidates])
    return [
        RankedChunk(
            chunk_id=c.chunk_id,
            article_id=c.article_id,
            article_slug=c.article_slug,
            content=c.content,
            shortlist_score=s,
        )
        for c, s in zip(candidates, scores, strict=True)
    ]


def _by_score(chunks: list[RankedChunk]) -> list[RankedChunk]:
    # Stable: equal scores keep their incoming order.
    return sorted(chunks, key=lambda r: r.shortlist_score, reverse=True)


class CandidatePoolNode(BaseNode):
    def __call__(self, state: TriageState) -> StateUpdate:
        candidates = state.candidates
        if not candidates:
            return {"pool": []}

        query = f"{state.ticket.subject_masked}\n{state.ticket.body_masked}"
        pool = _by_score(_scored(query, candidates))

        seeds = list(dict.fromkeys(r.article_id for r in pool[: settings.link_expansion_seeds]))
        # A DB failure raises: "no links" and "couldn't read links" are
        # different facts.
        linked = linked_article_ids(seeds, max_per_seed=settings.link_expansion_max_links_per_seed)
        added = nearest_chunks(
            linked, state.query_embedding, per_article=settings.link_expansion_chunks_per_page
        )

        seen = {c.chunk_id for c in candidates}
        added = [c for c in added if c.chunk_id not in seen]
        if added:
            pool = _by_score(pool + _scored(query, added))
        return {"pool": pool}


candidate_pool = CandidatePoolNode()
