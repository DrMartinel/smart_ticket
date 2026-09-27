"""
Retrieval-node tests. The distinction this file exists to protect: an
infrastructure failure (embedder down, DB unreachable) must never be
indistinguishable from an ordinary "the KB has nothing relevant". Those
carry different reason codes and route differently downstream.
"""

from __future__ import annotations

import pytest

from ai_engine.core.config import settings
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode


@pytest.fixture
def make_node(use_db, use_embedder):
    def make(db, embedder):
        use_db(db)
        use_embedder(embedder)
        return HybridRetrieveNode()

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


def test_bm25_keyword_hit_is_false_when_lexical_finds_nothing(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    """`bm25_keyword_hit` feeds the trust scorer. True on a pure-vector match
    inflates trust exactly where the evidence is weakest.
    """

    def rows(sql, params):
        return [] if "tsv" in sql else [kb_row(1, "a", 0.8)]

    node = make_node(fake_db(rows=rows), fake_embedder())

    out = node(make_state())

    assert out["bm25_keyword_hit"] is False
    assert len(out["candidates"]) == 1


def test_bm25_keyword_hit_is_true_when_lexical_matches(
    fake_db, fake_embedder, kb_row, make_state, make_node
):
    node = make_node(fake_db(rows=[kb_row(1, "a", 0.8)]), fake_embedder())

    assert node(make_state())["bm25_keyword_hit"] is True


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
    assert out["bm25_keyword_hit"] is False
    assert "degraded_reason" not in out
