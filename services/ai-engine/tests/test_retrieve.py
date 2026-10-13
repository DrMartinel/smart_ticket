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


def test_bm25_searches_the_draft_never_the_ticket(
    fake_db, fake_embedder, kb_row, make_state, make_ticket, make_node
):
    bm25_texts = []

    def rows(sql, params):
        if "|||" in sql:
            bm25_texts.append(params["content_1"])
        return [kb_row(1, "a", 0.8)]

    state = make_state(
        ticket=make_ticket("VPN down", "cannot reach"), draft_text="Client VPN routes"
    )
    make_node(fake_db(rows=rows), fake_embedder())(state)

    assert bm25_texts == ["Client VPN routes"]


def test_vector_search_runs_on_the_ticket_and_on_the_draft(
    fake_db, fake_embedder, kb_row, make_state, make_ticket, make_node
):
    embeddings = []

    def rows(sql, params):
        if "<=>" in sql:
            embeddings.append(params["embedding_1"])
        return [kb_row(1, "a", 0.8)]

    embedder = fake_embedder(vector=[0.9])
    make_node(fake_db(rows=rows), embedder)(make_state(draft_embedding=[0.1]))

    assert sorted(map(tuple, embeddings)) == [(0.1,), (0.9,)]
    # The draft arrives embedded (DraftAnswerNode); only the ticket is embedded here.
    assert len(embedder.calls) == 1


@pytest.mark.parametrize("missing", [{"draft_text": ""}, {"draft_embedding": []}])
def test_retrieval_without_a_draft_raises_rather_than_retrieving_on_the_ticket(
    fake_db, fake_embedder, kb_row, make_state, make_node, missing
):
    node = make_node(fake_db(rows=[kb_row(1, "a", 0.8)]), fake_embedder())

    with pytest.raises(ValueError, match="drafted answer"):
        node(make_state(**missing))


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


def test_candidates_are_one_chunk_per_page_in_fused_order(
    fake_db, fake_embedder, make_state, make_node
):
    a, b = UUID(int=100), UUID(int=200)
    vector_rows = [
        (UUID(int=1), a, "kb-a", "a1", 0.9),
        (UUID(int=2), a, "kb-a", "a2", 0.8),
        (UUID(int=3), a, "kb-a", "a3", 0.7),
        (UUID(int=4), b, "kb-b", "b1", 0.6),
    ]

    def rows(sql, params):
        return [] if "|||" in sql else vector_rows

    out = make_node(fake_db(rows=rows), fake_embedder())(make_state())

    assert [c.chunk_id for c in out["candidates"]] == [UUID(int=1), UUID(int=4)]


def test_the_candidate_limit_counts_pages_not_chunks(
    fake_db, fake_embedder, make_state, monkeypatch, make_node
):
    monkeypatch.setattr(settings, "fusion_candidate_limit", 2)
    a, b, c = UUID(int=100), UUID(int=200), UUID(int=300)
    vector_rows = [
        (UUID(int=1), a, "kb-a", "a1", 0.9),
        (UUID(int=2), a, "kb-a", "a2", 0.8),
        (UUID(int=3), b, "kb-b", "b1", 0.7),
        (UUID(int=4), c, "kb-c", "c1", 0.6),
    ]

    def rows(sql, params):
        return [] if "|||" in sql else vector_rows

    out = make_node(fake_db(rows=rows), fake_embedder())(make_state())

    assert [x.article_id for x in out["candidates"]] == [a, b]


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
    assert "degraded_reason" not in out


def test_query_embedding_stays_the_tickets_for_few_shots(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    out = make_node(fake_db(rows=[kb_row(1, "a", 0.8)]), fake_embedder(vector=[0.9]))(
        make_state(draft_embedding=[0.1])
    )

    assert out["query_embedding"] == [0.9]
