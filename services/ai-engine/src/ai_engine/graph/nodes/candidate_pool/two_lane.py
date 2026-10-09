"""
The two-lane shortlist (`SHORTLIST_STRATEGY=two_lane`): which chunks Jev
scores when link expansion is on.

In one pool, expansion's chunks compete with the retrieved ones on the
cross-encoder's relevance, which ranks pages *about* the ticket above the
page that *resolves* it; the 2026-10-08 probes lost fix pages that way
before Jev saw them (`evals/HISTORY.md`). Here each lane has its own slots:

- the **seed lane**: the fused candidates, by cross-encoder score;
- the **graph lane**: one chunk per linked page (its nearest to the ticket),
  by how strongly a relevant seed points to it, `max over parent seeds of
  (seed score x edge weight)`. An edge weight is the association's score
  over the highest among the ticket's edges.

Pure: no I/O. Every number here orders a lane; none is compared with a
threshold (ADR-0005), so there is deliberately no minimum graph score. Jev
scores each shortlisted chunk on its own, so the order the lanes are joined
in does not matter.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import NamedTuple

from ai_engine.graph.nodes.candidate_pool.links import Association
from ai_engine.graph.state import Candidate, RankedChunk


class Lanes(NamedTuple):
    """Jev's shortlist first, then every other chunk, best first per lane."""

    shortlist: list[RankedChunk]
    rest: list[RankedChunk]


def edge_weights(edges: Iterable[Association]) -> dict[tuple[uuid.UUID, uuid.UUID], float]:
    """(seed, target) -> score / the highest score among this ticket's
    edges, in (0, 1]. Per ticket, not per seed: one source is active per run
    (`ASSOCIATION_SOURCE`), so a query's edges share a scale, and a weak link
    that is its seed's only one must not weigh as much as another seed's
    strong link (normalized per seed, the design doc's own example dropped
    its fix chunk)."""

    edges = list(edges)
    best = max((e.score for e in edges), default=0.0)
    if best <= 0:
        return {}
    return {(e.seed, e.target): e.score / best for e in edges}


def propagated(
    graph_chunks: Iterable[Candidate],
    weights: Mapping[tuple[uuid.UUID, uuid.UUID], float],
    seed_scores: Mapping[uuid.UUID, float],
) -> list[RankedChunk]:
    """Each graph chunk scored `max over parents (seed score x weight)`. A
    chunk no scored seed points to is dropped: nothing places it."""

    scored: list[RankedChunk] = []
    for c in graph_chunks:
        props = [
            seed_scores[seed] * w
            for (seed, target), w in weights.items()
            if target == c.article_id and seed in seed_scores
        ]
        if props:
            scored.append(
                RankedChunk(
                    chunk_id=c.chunk_id,
                    article_id=c.article_id,
                    article_slug=c.article_slug,
                    content=c.content,
                    shortlist_score=max(props),
                )
            )
    return scored


def two_lane_shortlist(
    seeds: list[RankedChunk],
    graph: list[RankedChunk],
    *,
    seed_quota: int,
    graph_quota: int,
) -> Lanes:
    """The top `seed_quota` seeds and top `graph_quota` graph chunks; a lane
    short of its quota gives the slots to the other lane's next best. A
    chunk in both lanes stays a seed. Ties break on the chunk id, so the
    same pool gives the same shortlist."""

    def key(r: RankedChunk) -> tuple[float, str]:
        return (-r.shortlist_score, str(r.chunk_id))

    seed_ids = {r.chunk_id for r in seeds}
    seeds = sorted(seeds, key=key)
    graph = sorted((r for r in graph if r.chunk_id not in seed_ids), key=key)

    picked = seeds[:seed_quota] + graph[:graph_quota]
    rest = sorted(seeds[seed_quota:] + graph[graph_quota:], key=key)
    free = seed_quota + graph_quota - len(picked)
    return Lanes(shortlist=picked + rest[:free], rest=rest[free:])
