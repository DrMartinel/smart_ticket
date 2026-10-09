"""
The two-lane shortlist (`SHORTLIST_STRATEGY=two_lane`, `two_lane.py`). Its
point is that expansion's fix chunk reaches Jev even when the cross-encoder
would rank it below pages that are merely *about* the ticket (the 2026-10-08
probes lost g052/g053 that way). The design doc's worked example: a VPN
ticket whose fix (c5, a DNS command) the cross-encoder scores 0.22.

Edge weights are normalized per ticket (one source per run), so the doc's
raw weights 0.5 / 0.6 / 0.9 become 0.556 / 0.667 / 1.0.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from ai_engine.core.config import Settings, settings
from ai_engine.graph.nodes.candidate_pool.links import Association
from ai_engine.graph.nodes.candidate_pool.two_lane import (
    edge_weights,
    propagated,
    two_lane_shortlist,
)
from ai_engine.graph.state import Candidate, RankedChunk

A1, A2, P3, P4, P5, P6 = (UUID(int=i) for i in (101, 102, 103, 104, 105, 106))


def _id(n: int) -> UUID:
    return UUID(int=n)


def _seed(n: int, article: UUID, score: float) -> RankedChunk:
    return RankedChunk(
        chunk_id=_id(n),
        article_id=article,
        article_slug=str(article),
        content=f"c{n}",
        shortlist_score=score,
    )


def _graph(n: int, article: UUID) -> Candidate:
    return Candidate(
        chunk_id=_id(n), article_id=article, article_slug=str(article), content=f"c{n}"
    )


SEEDS = [_seed(1, A1, 0.91), _seed(2, A2, 0.74)]
SEED_SCORES = {A1: 0.91, A2: 0.74}
EDGES = [Association(A2, P3, 0.5), Association(A1, P4, 0.6), Association(A2, P5, 0.9)]
GRAPH = [_graph(3, P3), _graph(4, P4), _graph(5, P5)]


def _ids(chunks: list[RankedChunk]) -> list[int]:
    return [c.chunk_id.int for c in chunks]


def _lanes(graph: list[RankedChunk], *, seeds=SEEDS, seed_quota=2, graph_quota=1):
    return two_lane_shortlist(seeds, graph, seed_quota=seed_quota, graph_quota=graph_quota)


def test_the_fix_reaches_jev_through_the_graph_lane():
    """T2. In one pool ranked by the cross-encoder (c1 0.91, c2 0.74, c3 0.70,
    c4 0.68, c5 0.22) the top 3 never hold c5. Propagated, c5 = 0.74 x 1.0."""
    graph = propagated(GRAPH, edge_weights(EDGES), SEED_SCORES)

    lanes = _lanes(graph)

    assert _ids(lanes.shortlist) == [1, 2, 5]
    assert lanes.shortlist[2].shortlist_score == pytest.approx(0.74)
    assert _ids(lanes.rest) == [4, 3]  # c4 0.607, c3 0.411


def test_a_chunk_linked_from_several_seeds_takes_its_strongest_parent():
    """T3. max(0.91 x 0.3/0.9, 0.74 x 0.9/0.9) = 0.74."""
    edges = [*EDGES, Association(A1, P5, 0.3)]

    [c5] = [c for c in propagated(GRAPH, edge_weights(edges), SEED_SCORES) if c.chunk_id.int == 5]

    assert c5.shortlist_score == pytest.approx(0.74)


def test_a_chunk_in_both_lanes_stays_a_seed_once():
    """T4: Jev must not score the same chunk twice, and the seed's own
    cross-encoder score is the better evidence."""
    graph = propagated(
        [*GRAPH, _graph(2, A2)], edge_weights([*EDGES, Association(A1, A2, 0.9)]), SEED_SCORES
    )

    lanes = _lanes(graph)

    assert _ids(lanes.shortlist + lanes.rest).count(2) == 1
    assert next(c for c in lanes.shortlist if c.chunk_id.int == 2).shortlist_score == 0.74


def test_with_no_graph_chunks_the_seeds_fill_the_slots():
    """T5: a KB without associations must not shortlist fewer chunks."""
    seeds = [*SEEDS, _seed(6, P6, 0.40)]

    lanes = _lanes([], seeds=seeds)

    assert _ids(lanes.shortlist) == [1, 2, 6]


def test_with_few_seeds_the_graph_lane_fills_the_slots():
    lanes = _lanes(propagated(GRAPH, edge_weights(EDGES), SEED_SCORES), seeds=SEEDS[:1])

    assert _ids(lanes.shortlist) == [1, 5, 4]


def test_ties_break_on_the_chunk_id():
    """T8: the same pool must give the same shortlist."""
    edges = [Association(A2, P3, 0.9), Association(A2, P5, 0.9)]

    lanes = _lanes(propagated(GRAPH, edge_weights(edges), SEED_SCORES))

    assert _ids(lanes.shortlist)[-1] == 3


def test_a_graph_chunk_no_scored_seed_points_to_is_dropped():
    """Nothing places it, so it must not take a slot by default."""
    graph = propagated([_graph(6, P6)], edge_weights(EDGES), SEED_SCORES)

    assert graph == []


def test_edge_weights_are_relative_to_the_ticket_strongest_edge():
    weights = edge_weights(EDGES)

    assert weights[(A2, P5)] == 1.0
    assert weights[(A1, P4)] == pytest.approx(0.6 / 0.9)
    assert edge_weights([]) == {}


def test_two_lane_quotas_must_fill_rerank_pool():
    """A mismatch would quietly change how many chunks Jev scores. Init
    arguments outrank the environment and `.env`."""
    with pytest.raises(ValidationError, match="must equal RERANK_POOL"):
        Settings(
            shortlist_strategy="two_lane",
            shortlist_seed_quota=10,
            shortlist_graph_quota=6,
            rerank_pool=15,
        )  # type: ignore[call-arg]

    Settings(
        shortlist_strategy="two_lane",
        shortlist_seed_quota=10,
        shortlist_graph_quota=5,
        rerank_pool=15,
    )  # type: ignore[call-arg]


# --- the node --------------------------------------------------------------


def test_the_node_cross_encodes_only_the_seeds_and_puts_the_two_lane_shortlist_first(
    fake_db, fake_shortlister, make_candidate, make_state, use_db, use_shortlister, monkeypatch
):
    """Expansion's chunks are placed by propagation, so the cross-encoder
    scores the fused candidates only: a smaller batch, and none of
    expansion's pages can outrank the fix on relevance alone."""
    monkeypatch.setattr(settings, "shortlist_strategy", "two_lane")
    monkeypatch.setattr(settings, "shortlist_seed_quota", 1)
    monkeypatch.setattr(settings, "shortlist_graph_quota", 1)
    monkeypatch.setattr(settings, "link_expansion_seeds", 1)
    monkeypatch.setattr(settings, "association_source", "entity_graph")
    seed = make_candidate(1)
    linked = _graph(9, P5)

    def rows(sql, params):
        if "kb_article_associations" in sql:
            return [(seed.article_id, P5, 6.4)]
        if "row_number" in sql:  # nearest_chunks
            return [(linked.chunk_id, P5, linked.article_slug, linked.content)]
        return []

    use_db(fake_db(rows))
    shortlister = use_shortlister(fake_shortlister(scores=[0.8, 0.3]))
    from ai_engine.graph.nodes.candidate_pool.node import candidate_pool

    pool = candidate_pool(make_state(candidates=[seed, make_candidate(2)]))["pool"]

    assert [len(passages) for _, passages in shortlister.calls] == [2]
    assert [c.chunk_id for c in pool[:2]] == [seed.chunk_id, linked.chunk_id]
    assert pool[1].shortlist_score == pytest.approx(0.8)
