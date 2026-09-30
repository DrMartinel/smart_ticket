"""
Rerank-node tests. This node owns the refuse-before-LLM decision's input:
`reranked[0].score` is the number RerankNode.decide compares against
`retrieval_floor`, so anything that corrupts the ordering or the score
silently changes how often the LLM is called at all.
"""

from __future__ import annotations

from uuid import UUID

from ai_engine.core.config import settings
from ai_engine.core.retrieval.fusion import Candidate
from ai_engine.graph.nodes.rerank import rerank


def _chunk(chunk_id: int, article: int) -> Candidate:
    """A candidate belonging to `article`; `make_candidate` gives every
    chunk its own article, which can't exercise the per-article dedup."""

    return Candidate(
        chunk_id=UUID(int=chunk_id),
        article_id=UUID(int=article),
        article_slug=f"kb-{article}",
        content=f"chunk {chunk_id}",
    )


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

    assert [r.chunk_id for r in reranked] == [UUID(int=3), UUID(int=2), UUID(int=1)]
    assert reranked[0].score == 0.9


def test_truncation_uses_the_configured_top_n(
    fake_reranker, make_candidate, make_state, monkeypatch, use_reranker
):
    monkeypatch.setattr(settings, "rerank_top_n", 2)
    candidates = [make_candidate(i, f"c{i}") for i in (1, 2, 3, 4)]
    use_reranker(fake_reranker(scores=[0.1, 0.9, 0.5, 0.7]))
    node = rerank

    reranked = node(make_state(candidates=candidates))["reranked"]

    assert [r.chunk_id for r in reranked] == [UUID(int=2), UUID(int=4)]


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
    assert by_id == {UUID(int=7): 0.2, UUID(int=8): 0.8}


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


# --- one chunk per article ------------------------------------------------------


def test_dedup_never_changes_the_top_chunk(fake_reranker, make_state, use_reranker):
    """`decide()` compares `reranked[0].score` with the floor, so dedup must
    leave the best chunk overall in first place. Candidates arrive with the
    best chunk LAST in RRF order: keeping each article's first chunk in RRF
    order instead of by cross-encoder score would put 0.4 on top, and the
    floor would refuse a ticket with 0.9 evidence (ADR-0005)."""

    candidates = [_chunk(1, article=1), _chunk(2, article=2), _chunk(3, article=1)]
    use_reranker(fake_reranker(scores=[0.4, 0.6, 0.9]))

    reranked = rerank(make_state(candidates=candidates))["reranked"]

    assert reranked[0].chunk_id == UUID(int=3)
    assert reranked[0].score == 0.9


def test_one_article_cannot_fill_every_slot(fake_reranker, make_state, use_reranker):
    """Three chunks of one article outscoring another article must not take
    all three slots: the LLM would see a single source, and a quote from any
    other page would fail as `quote_source_not_in_topk`."""

    candidates = [_chunk(1, 1), _chunk(2, 1), _chunk(3, 1), _chunk(4, 2), _chunk(5, 3)]
    use_reranker(fake_reranker(scores=[0.9, 0.8, 0.7, 0.5, 0.3]))

    reranked = rerank(make_state(candidates=candidates))["reranked"]

    assert [r.article_id for r in reranked] == [UUID(int=1), UUID(int=2), UUID(int=3)]
    assert [r.chunk_id for r in reranked] == [UUID(int=1), UUID(int=4), UUID(int=5)]


def test_dedup_keeps_each_articles_highest_scoring_chunk(fake_reranker, make_state, use_reranker):
    """The chunk kept for an article is its best by cross-encoder score, not
    the one RRF happened to list first (ADR-0005)."""

    candidates = [_chunk(1, 1), _chunk(2, 2), _chunk(3, 2), _chunk(4, 1)]
    use_reranker(fake_reranker(scores=[0.2, 0.3, 0.6, 0.8]))

    reranked = rerank(make_state(candidates=candidates))["reranked"]

    assert {r.article_id: r.chunk_id for r in reranked} == {
        UUID(int=1): UUID(int=4),
        UUID(int=2): UUID(int=3),
    }


def test_fewer_articles_than_top_n_returns_fewer_chunks(fake_reranker, make_state, use_reranker):
    """Two articles give two chunks, not three: refilling the last slot with a
    second chunk of an article already shown would bring the crowding back."""

    candidates = [_chunk(1, 1), _chunk(2, 1), _chunk(3, 2), _chunk(4, 2)]
    use_reranker(fake_reranker(scores=[0.9, 0.8, 0.7, 0.6]))

    reranked = rerank(make_state(candidates=candidates))["reranked"]

    assert [r.chunk_id for r in reranked] == [UUID(int=1), UUID(int=3)]
