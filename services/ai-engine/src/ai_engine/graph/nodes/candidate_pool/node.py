"""
Candidate pool — the cross-encoder pass, and link expansion (ADR-0014
decisions 1-2, ADR-0015, ADR-0018). The cross-encoder scores the fused
candidates; the articles of its top `link_expansion_seeds` chunks are the
seeds; the articles associated with them (in the one source
`ASSOCIATION_SOURCE` names) add their chunks nearest the ticket; the
cross-encoder scores those too. The pool leaves in cross-encoder order, for RerankNode to cut to
Jev's shortlist and re-score.

Under `SHORTLIST_STRATEGY=two_lane` the cross-encoder scores the fused
candidates only, and expansion's chunks are placed by propagation from the
seeds instead (`two_lane.py`): the pool leaves with that shortlist first.

Every score here is the cross-encoder's or derived from it, and only orders.
Seeds come from its order, never from RRF's (ADR-0005).
"""

from __future__ import annotations

import uuid
from typing import Any

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.nodes.candidate_pool.links import (
    associations,
    linked_article_ids,
    nearest_chunks,
)
from ai_engine.graph.nodes.candidate_pool.shortlister import shortlister
from ai_engine.graph.nodes.candidate_pool.two_lane import (
    edge_weights,
    propagated,
    two_lane_shortlist,
)
from ai_engine.graph.state import Candidate, RankedChunk, TriageState


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
    return sorted(chunks, key=lambda r: r.shortlist_score, reverse=True)


def _two_lane_pool(
    state: TriageState, seed_lane: list[RankedChunk], seeds: list[uuid.UUID]
) -> list[RankedChunk]:
    """The pool with the two-lane shortlist first (`two_lane.py`). Only the
    fused candidates are scored by the cross-encoder; each linked page adds
    its one chunk nearest the ticket, placed by propagation."""

    edges = associations(seeds, max_per_seed=settings.link_expansion_max_links_per_seed)
    targets = list(dict.fromkeys(e.target for e in edges))
    seed_scores: dict[uuid.UUID, float] = {}
    for r in seed_lane:
        if r.article_id in seeds:
            seed_scores[r.article_id] = max(seed_scores.get(r.article_id, 0.0), r.shortlist_score)
    graph = propagated(
        nearest_chunks(targets, state.query_embedding, per_article=1),
        edge_weights(edges),
        seed_scores,
    )
    lanes = two_lane_shortlist(
        seed_lane,
        graph,
        seed_quota=settings.shortlist_seed_quota,
        graph_quota=settings.shortlist_graph_quota,
    )
    return lanes.shortlist + lanes.rest


class CandidatePoolNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        candidates = state.candidates
        if not candidates:
            return {"pool": []}

        query = f"{state.ticket.subject_masked}\n{state.ticket.body_masked}"
        pool = _by_score(_scored(query, candidates))

        seeds = list(dict.fromkeys(r.article_id for r in pool[: settings.link_expansion_seeds]))
        if settings.shortlist_strategy == "two_lane":
            return {"pool": _two_lane_pool(state, pool, seeds)}
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
