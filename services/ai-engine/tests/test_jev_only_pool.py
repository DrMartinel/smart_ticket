"""
`SHORTLIST_PROVIDER=none`: Jev, the reranker, is the only scorer. It scores
the fused candidates, the articles of its top chunks seed link expansion,
and it scores what expansion adds; RerankNode then only cuts. The bugs this
guards against are quiet: seeds taken from RRF's order (ADR-0005), a chunk
leaving the pool with no Jev score (the floor would have nothing to compare,
or would compare the wrong thing), or a failed second pass shrinking the
pool to the first.
"""

from __future__ import annotations

import threading
import time
from uuid import UUID

import pytest

from ai_engine.core.config import settings
from ai_engine.graph.nodes.candidate_pool import node as pool_node
from ai_engine.graph.nodes.candidate_pool.node import candidate_pool
from ai_engine.graph.nodes.rerank import reranker as reranker_module
from ai_engine.graph.nodes.rerank.node import rerank
from ai_engine.graph.nodes.rerank.reranker import JevReranker, Passage


class ScriptedJev:
    """One reply per call: a list of scores, or an exception. Records the
    passages of each call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[list[str]] = []

    def score(self, subject, body, passages):
        self.calls.append([p.text for p in passages])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def jev_only(monkeypatch, fake_db, use_db, use_reranker):
    """No shortlister; associations and nearest chunks are canned, so these
    tests see only the node's logic."""

    monkeypatch.setattr(settings, "shortlist_provider", "none")
    monkeypatch.setattr(settings, "link_expansion_seeds", 1)
    use_db(fake_db())
    linked_from: list[list[UUID]] = []

    def install(jev, linked=(), added=()):
        use_reranker(jev)

        def fake_linked(seeds, *, max_per_seed):
            linked_from.append(list(seeds))
            return list(linked)

        monkeypatch.setattr(pool_node, "linked_article_ids", fake_linked)
        monkeypatch.setattr(
            pool_node, "nearest_chunks", lambda ids, emb, *, per_article: list(added)
        )
        return linked_from

    return install


# --- failure paths first ------------------------------------------------------


def test_a_failed_second_pass_fails_the_run_not_the_pool(jev_only, make_candidate, make_state):
    """Keeping pass 1's chunks when pass 2 fails would hand on a smaller pool
    with nothing looking wrong. The run fails: HITL as ai_engine_unavailable."""

    jev_only(
        ScriptedJev([0.9, 0.1], RuntimeError("jev down")),
        linked=[UUID(int=99)],
        added=[make_candidate(9, "linked")],
    )

    with pytest.raises(RuntimeError, match="jev down"):
        candidate_pool(make_state(candidates=[make_candidate(1, "a"), make_candidate(2, "b")]))


def test_a_short_jev_reply_raises(jev_only, make_candidate, make_state):
    jev_only(ScriptedJev([0.9]))

    with pytest.raises(ValueError, match="1 scores for 2"):
        candidate_pool(make_state(candidates=[make_candidate(1, "a"), make_candidate(2, "b")]))


def test_no_candidates_makes_no_jev_call(jev_only, make_state):
    jev = ScriptedJev()
    jev_only(jev)

    assert candidate_pool(make_state(candidates=[])) == {"pool": []}
    assert jev.calls == []


# --- behaviour ------------------------------------------------------------------


def test_seeds_come_from_jevs_order_not_rrfs(jev_only, make_candidate, make_state):
    """ADR-0005: the candidates arrive in RRF order. Jev inverts it, so the
    seed must be the article of the chunk Jev ranked first, the last one in."""

    linked_from = jev_only(ScriptedJev([0.1, 0.2, 0.9]))
    candidates = [make_candidate(1, "a"), make_candidate(2, "b"), make_candidate(3, "c")]

    candidate_pool(make_state(candidates=candidates))

    assert linked_from == [[candidates[2].article_id]]


def test_every_chunk_leaves_scored_by_jev_in_jevs_order(jev_only, make_candidate, make_state):
    """Pass 2's chunks merge into pass 1's by Jev's score. A linked chunk
    that is already a fused candidate is not scored again."""

    jev = ScriptedJev([0.5, 0.2], [0.7])
    jev_only(
        jev,
        linked=[UUID(int=99)],
        added=[make_candidate(1, "a"), make_candidate(9, "linked")],
    )

    pool = candidate_pool(make_state(candidates=[make_candidate(1, "a"), make_candidate(2, "b")]))[
        "pool"
    ]

    assert jev.calls == [["a", "b"], ["linked"]]
    assert [(r.chunk_id.int, r.final_score()) for r in pool] == [(9, 0.7), (1, 0.5), (2, 0.2)]
    assert all(r.shortlist_score == r.rerank_score for r in pool)


def test_the_rerank_node_only_cuts_the_scored_pool(
    jev_only, make_candidate, make_state, monkeypatch
):
    """RerankNode must not ask Jev again: the pool is already scored, and a
    second call would double the cost and could reorder nothing."""

    monkeypatch.setattr(settings, "rerank_top_n", 2)
    jev = ScriptedJev([0.3, 0.8, 0.6])
    jev_only(jev)
    pool = candidate_pool(
        make_state(
            candidates=[make_candidate(1, "a"), make_candidate(2, "b"), make_candidate(3, "c")]
        )
    )["pool"]

    reranked = rerank(make_state(pool=pool))["reranked"]

    assert len(jev.calls) == 1
    assert [(r.chunk_id.int, r.final_score()) for r in reranked] == [(2, 0.8), (3, 0.6)]


def test_jev_requests_in_flight_never_exceed_the_limit(monkeypatch):
    """One request per chunk; a whole pool (up to ~170) at once would hit
    Jev's rate limit, and a 429 fails the run."""

    monkeypatch.setattr(settings, "jev_max_concurrency", 3)
    lock, in_flight, peak = threading.Lock(), [0], [0]

    class CountingJev:
        def ask(self, state, questions):
            with lock:
                in_flight[0] += 1
                peak[0] = max(peak[0], in_flight[0])
            time.sleep(0.01)
            with lock:
                in_flight[0] -= 1
            return {"resolves": 0.5}

    monkeypatch.setattr(reranker_module.clients, "jev", CountingJev())

    scores = JevReranker().score("s", "b", [Passage("t", str(i)) for i in range(12)])

    assert scores == [0.5] * 12
    assert peak[0] == 3
