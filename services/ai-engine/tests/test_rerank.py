"""
Rerank-node tests. This node owns the refuse-before-LLM decision's input:
`reranked[0].score` is the number RerankNode.decide compares against
`retrieval_floor`, so anything that corrupts the ordering or the score
silently changes how often the LLM is called at all.
"""

from __future__ import annotations

from ai_engine.core.config import settings
from ai_engine.graph.nodes.rerank import rerank


def test_output_order_follows_the_reranker_not_the_rrf_order(
    fake_reranker, make_candidate, make_state, use_reranker
):
    """ADR-0005: candidates arrive in RRF order, which means nothing for
    thresholds; the node must reorder by cross-encoder score. Dropping the
    sort fails silently — the floor would be compared against whichever
    chunk RRF ranked first.
    """

    candidates = [make_candidate(1, "a"), make_candidate(2, "b"), make_candidate(3, "c")]
    # Scores INVERT the incoming RRF order.
    use_reranker(fake_reranker(scores=[0.1, 0.5, 0.9]))
    node = rerank

    reranked = node(make_state(candidates=candidates))["reranked"]

    assert [r.chunk_id for r in reranked] == [3, 2, 1]
    assert reranked[0].score == 0.9


def test_truncation_uses_the_configured_top_n(
    fake_reranker, make_candidate, make_state, monkeypatch, use_reranker
):
    monkeypatch.setattr(settings, "rerank_top_n", 2)
    candidates = [make_candidate(i, f"c{i}") for i in (1, 2, 3, 4)]
    use_reranker(fake_reranker(scores=[0.1, 0.9, 0.5, 0.7]))
    node = rerank

    reranked = node(make_state(candidates=candidates))["reranked"]

    assert [r.chunk_id for r in reranked] == [2, 4]


def test_empty_candidates_returns_empty_without_a_degraded_reason(
    fake_reranker, make_state, use_reranker
):
    """An empty KB is an ordinary refuse-before-LLM with its own reason code.
    Setting degraded_reason would mislabel it as a system failure on the
    HITL dashboard.
    """

    reranker = fake_reranker(scores=[0.9])
    use_reranker(reranker)
    node = rerank

    out = node(make_state(candidates=[]))

    assert out == {"reranked": []}
    assert "degraded_reason" not in out
    assert reranker.calls == []


def test_scores_are_zipped_to_candidates_positionally(
    fake_reranker, make_candidate, make_state, use_reranker
):
    """The provider contract is one score per passage in input order. This
    pins that the node pairs them positionally — a mismatch would attach the
    wrong score to the wrong chunk while everything still looks sorted."""

    candidates = [make_candidate(7, "seven"), make_candidate(8, "eight")]
    use_reranker(fake_reranker(scores=[0.2, 0.8]))
    node = rerank

    reranked = node(make_state(candidates=candidates))["reranked"]

    by_id = {r.chunk_id: r.score for r in reranked}
    assert by_id == {7: 0.2, 8: 0.8}


def test_query_sent_to_the_reranker_is_the_masked_ticket(
    fake_reranker, make_candidate, make_state, make_ticket, use_reranker
):
    """Only masked text may leave core-api's boundary — the reranker must
    never be handed raw PII."""

    reranker = fake_reranker(scores=[0.5])
    use_reranker(reranker)
    node = rerank

    node(make_state(candidates=[make_candidate(1, "a")], ticket=make_ticket("subj", "body")))

    query, passages = reranker.calls[0]
    assert query == "subj\nbody"
    assert passages == ["a"]
