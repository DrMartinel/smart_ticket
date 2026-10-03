"""
Retrieval-node tests. The distinction this file exists to protect: an
infrastructure failure (embedder down, DB unreachable) must never be
indistinguishable from an ordinary "the KB has nothing relevant". Those
carry different reason codes and route differently downstream.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from ai_engine.core.config import settings
from ai_engine.graph.nodes.retrieve.node import hybrid_retrieve


@pytest.fixture
def make_node(use_db, use_embedder):
    def make(db, embedder):
        use_db(db)
        use_embedder(embedder)
        return hybrid_retrieve

    return make


def test_embedder_failure_propagates_rather_than_returning_empty_candidates(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    """An embedder outage must not become an empty candidate list, which routes
    as an ordinary refuse-before-LLM. An infrastructure degrade has to be
    visible as one — the retrieval cousin of mask_failed resolving to "no
    PII found".
    """

    embedder = fake_embedder(error=RuntimeError("vllm unreachable"))
    node = make_node(fake_db(rows=[kb_row(1, "a", 0.9)]), embedder)

    with pytest.raises(RuntimeError, match="vllm unreachable"):
        node(make_state())


def test_bm25_query_failure_propagates_rather_than_running_vector_only(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    """A BM25 query that errors (pg_search not installed or not preloaded,
    a permissions error on its `pdb` schema) must fail the run, not fall back
    to vector-only retrieval. That silent fallback is the exact bug ADR-0013
    fixes: hybrid retrieval quietly running on one channel, with nothing
    reporting it.
    """

    def rows(sql, params):
        if "|||" in sql:
            raise RuntimeError("pg_search must be loaded via shared_preload_libraries")
        return [kb_row(1, "a", 0.8)]

    node = make_node(fake_db(rows=rows), fake_embedder())

    with pytest.raises(RuntimeError, match="shared_preload_libraries"):
        node(make_state())


def test_no_db_connection_is_held_while_embedding(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    """The embedder is an HTTP call to vLLM that can take the full read
    timeout. A connection held across it sits idle in transaction and out
    of the pool for that long; under load that starves every other ticket."""

    db = fake_db(rows=[kb_row(1, "a", 0.9)])
    open_while_embedding = []

    class Spy(fake_embedder):
        def embed(self, text):
            open_while_embedding.append(db.events.count("open") - db.events.count("close"))
            return super().embed(text)

    make_node(db, Spy())(make_state())

    assert open_while_embedding == [0]


def test_bm25_article_ids_are_empty_when_lexical_finds_nothing(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    """No lexical match must leave nothing for emit_signals to rank against,
    so it reports no agreement. Recording the vector hits' articles here
    would claim the two channels agree when only one of them ran."""

    def rows(sql, params):
        return [] if "|||" in sql else [kb_row(1, "a", 0.8)]

    node = make_node(fake_db(rows=rows), fake_embedder())

    out = node(make_state())

    assert out["bm25_article_ids"] == []
    assert len(out["candidates"]) == 1


def test_bm25_article_ids_are_deduplicated_in_bm25_order(
    fake_db, fake_embedder, make_state, make_node
):
    """The agreement rank counts ARTICLES. Three chunks of article A ahead of
    article B must put B second, not fourth; otherwise a long article
    crowding BM25's list pushes every other article past `k`."""

    a, b = UUID(int=100), UUID(int=200)
    bm25_rows = [
        (UUID(int=1), a, "kb-a", "a1", 9.0),
        (UUID(int=2), a, "kb-a", "a2", 8.0),
        (UUID(int=3), a, "kb-a", "a3", 7.0),
        (UUID(int=4), b, "kb-b", "b1", 6.0),
    ]

    def rows(sql, params):
        return bm25_rows if "|||" in sql else []

    out = make_node(fake_db(rows=rows), fake_embedder())(make_state())

    assert out["bm25_article_ids"] == [a, b]


def test_candidates_capped_at_the_configured_limit(
    fake_db, fake_embedder, kb_row, make_state, monkeypatch, make_node
):
    """The cap is the cross-encoder's batch size, so an uncapped list is
    a direct cost and latency regression."""

    monkeypatch.setattr(settings, "fusion_candidate_limit", 3)
    rows = [kb_row(i, f"c{i}", 1.0 / i) for i in range(1, 12)]
    node = make_node(fake_db(rows=rows), fake_embedder())

    assert len(node(make_state())["candidates"]) == 3


def test_embedding_query_is_the_masked_ticket(
    fake_db, fake_embedder, make_state, make_ticket, make_node
):
    """Only masked text may cross into ai-engine's providers."""

    embedder = fake_embedder()
    node = make_node(fake_db(), embedder)

    node(make_state(ticket=make_ticket("subj", "body")))

    assert embedder.calls == ["subj\nbody"]


def test_no_hits_at_all_yields_no_candidates_and_no_degraded_reason(
    fake_db, fake_embedder, make_state, make_node
):
    """An empty KB is a legitimate outcome, not a failure — it routes to
    refuse-before-LLM, which is the cheap, safe path."""

    out = make_node(fake_db(rows=[]), fake_embedder())(make_state())

    assert out["candidates"] == []
    assert out["bm25_article_ids"] == []
    assert "degraded_reason" not in out
