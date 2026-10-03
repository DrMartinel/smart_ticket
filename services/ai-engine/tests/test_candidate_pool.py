"""
Candidate-pool tests: the shortlister (cross-encoder) pass. The pool's order
is what RerankNode cuts to Jev's shortlist, so anything that corrupts it
silently changes which chunks the reranker ever sees.
"""

from __future__ import annotations

from uuid import UUID

from ai_engine.graph.nodes.candidate_pool.node import candidate_pool


def test_output_order_follows_the_reranker_not_the_rrf_order(
    fake_shortlister, make_candidate, make_state, use_shortlister
):
    """ADR-0005: candidates arrive in RRF order, which means nothing for
    thresholds; the node must order the pool by cross-encoder score. Dropping the
    sort fails silently — the floor would be compared against whichever
    chunk RRF ranked first.
    """

    candidates = [make_candidate(1, "a"), make_candidate(2, "b"), make_candidate(3, "c")]
    # Scores INVERT the incoming RRF order.
    use_shortlister(fake_shortlister(scores=[0.1, 0.5, 0.9]))
    node = candidate_pool

    pool = node(make_state(candidates=candidates))["pool"]

    assert [r.chunk_id for r in pool] == [UUID(int=3), UUID(int=2), UUID(int=1)]
    assert pool[0].shortlist_score == 0.9


def test_empty_candidates_returns_empty_without_a_degraded_reason(
    fake_shortlister, make_state, use_shortlister
):
    """An empty KB is an ordinary refuse-before-LLM with its own reason code.
    Setting degraded_reason would mislabel it as a system failure on the
    HITL dashboard.
    """

    shortlister = fake_shortlister(scores=[0.9])
    use_shortlister(shortlister)
    node = candidate_pool

    out = node(make_state(candidates=[]))

    assert out == {"pool": []}
    assert "degraded_reason" not in out
    assert shortlister.calls == []


def test_scores_are_zipped_to_candidates_positionally(
    fake_shortlister, make_candidate, make_state, use_shortlister
):
    """The provider contract is one score per passage in input order. This
    pins that the node pairs them positionally — a mismatch would attach the
    wrong score to the wrong chunk while everything still looks sorted."""

    candidates = [make_candidate(7, "seven"), make_candidate(8, "eight")]
    use_shortlister(fake_shortlister(scores=[0.2, 0.8]))
    node = candidate_pool

    pool = node(make_state(candidates=candidates))["pool"]

    by_id = {r.chunk_id: r.shortlist_score for r in pool}
    assert by_id == {UUID(int=7): 0.2, UUID(int=8): 0.8}


def test_query_sent_to_the_reranker_is_the_masked_ticket(
    fake_shortlister, make_candidate, make_state, make_ticket, use_shortlister
):
    """Only masked text may leave core-api's boundary — the shortlister must
    never be handed raw PII."""

    shortlister = fake_shortlister(scores=[0.5])
    use_shortlister(shortlister)
    node = candidate_pool

    node(make_state(candidates=[make_candidate(1, "a")], ticket=make_ticket("subj", "body")))

    query, passages = shortlister.calls[0]
    assert query == "subj\nbody"
    assert passages == ["a"]
