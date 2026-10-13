"""
Rerank-node tests. Jev ranks the cross-encoder's top `rerank_pool` chunks
of the pool with one choice question and is final (ADR-0026):
`reranked[0].final_score()` is the number the floor gate compares, on Jev's
scale. So the node must never hand on a chunk Jev didn't score, nor fall
back to the cross-encoder's order (ADR-0005).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from ai_engine.core.config import settings
from ai_engine.graph.state import RankedChunk
from ai_engine.graph.nodes.rerank.node import rerank


def _ranked(chunk_id: int, score: float) -> RankedChunk:
    return RankedChunk(
        chunk_id=UUID(int=chunk_id),
        article_id=UUID(int=chunk_id * 10),
        article_slug=f"kb-{chunk_id}",
        content=f"c{chunk_id}",
        shortlist_score=score,
    )


@pytest.fixture
def jev(fake_db, fake_reranker, use_db, use_reranker):
    """A fake Jev and the DB its passage titles come from."""

    def install(scores=None, error=None, **kw):
        use_db(fake_db())
        return use_reranker(fake_reranker(scores=scores, error=error, **kw))

    return install


# --- failure paths first ------------------------------------------------------


def test_a_jev_failure_propagates_rather_than_keeping_the_cross_encoder_order(jev, make_state):
    """Falling back to the cross-encoder's order would hand decide() chunks
    with no Jev score, compared against a floor set on Jev's scale. The run
    fails instead (HITL as `ai_engine_unavailable`)."""

    jev(error=RuntimeError("jev down"))

    with pytest.raises(RuntimeError, match="jev down"):
        rerank(make_state(pool=[_ranked(1, 0.9)]))


def test_a_short_jev_reply_raises(jev, make_state):
    """Zipping fewer scores than chunks would drop chunks silently, or pair
    a score with the wrong one."""

    jev(scores=[0.9])

    with pytest.raises(ValueError, match="1 scores for 2"):
        rerank(make_state(pool=[_ranked(1, 0.9), _ranked(2, 0.8)]))


def test_an_empty_pool_makes_no_jev_call(jev, make_state):
    """Nothing to score: no paid round-trip, and nothing above the floor."""

    fake = jev()

    out = rerank(make_state(pool=[]))

    assert out["reranked"] == []
    assert fake.calls == []


def test_jev_choosing_none_leaves_no_rerank_choice(jev, make_state):
    """Checks that a `none` choice names no page."""

    jev(scores=[0.9, 0.1], chooses_none=True)

    out = rerank(make_state(pool=[_ranked(1, 0.9), _ranked(2, 0.8)]))

    assert out["rerank_choice"] is None


# --- behaviour ------------------------------------------------------------------


def test_jev_ranks_only_the_cross_encoders_shortlist(jev, make_state, monkeypatch):
    """`rerank_pool` is a cost limit on Jev's options, cut from the
    cross-encoder's order."""

    monkeypatch.setattr(settings, "rerank_pool", 2)
    fake = jev(scores=[0.5, 0.6])

    rerank(make_state(pool=[_ranked(1, 0.9), _ranked(2, 0.8), _ranked(3, 0.7)]))

    [(_, _, passages)] = fake.calls
    assert [p.text for p in passages] == ["c1", "c2"]


def test_jev_orders_and_scores_keeping_the_cross_encoder_score(jev, make_state, monkeypatch):
    """Jev's order and score are final: the chunk the cross-encoder ranked
    last but Jev first leads `reranked`. Each chunk keeps its cross-encoder
    score beside Jev's, so a run shows what Jev changed."""

    monkeypatch.setattr(settings, "rerank_top_n", 3)
    jev(scores=[0.1, 0.2, 0.95])
    pool = [_ranked(1, 0.9), _ranked(2, 0.8), _ranked(3, 0.7)]

    out = rerank(make_state(pool=pool))

    reranked = out["reranked"]
    assert [r.chunk_id for r in reranked] == [UUID(int=3), UUID(int=2), UUID(int=1)]
    assert [(r.shortlist_score, r.rerank_score) for r in reranked] == [
        (0.7, 0.95),
        (0.8, 0.2),
        (0.9, 0.1),
    ]


def test_one_jev_call_ranks_the_shortlist_on_the_masked_ticket(jev, make_state):
    fake = jev(scores=[0.5, 0.4, 0.1])
    state = make_state(pool=[_ranked(1, 0.9), _ranked(2, 0.8), _ranked(3, 0.7)])

    rerank(state)

    [(subject, body, passages)] = fake.calls
    assert (subject, body) == (state.ticket.subject_masked, state.ticket.body_masked)
    assert len(passages) == 3


def test_equal_jev_scores_keep_the_cross_encoder_order(jev, make_state, monkeypatch):
    """Checks that chunks Jev scores alike stay in the cross-encoder's order."""

    monkeypatch.setattr(settings, "rerank_top_n", 4)
    jev(scores=[0.0, 0.9, 0.0, 0.0])
    pool = [_ranked(1, 0.9), _ranked(2, 0.8), _ranked(3, 0.7), _ranked(4, 0.6)]

    out = rerank(make_state(pool=pool))

    assert [r.chunk_id for r in out["reranked"]] == [UUID(int=i) for i in (2, 1, 3, 4)]


def test_jevs_choice_and_confidence_are_kept(jev, make_state):
    jev(scores=[0.1, 0.85], confidence=0.8)

    out = rerank(make_state(pool=[_ranked(1, 0.9), _ranked(2, 0.8)]))

    assert (out["rerank_choice"], out["rerank_confidence"]) == ("kb-2", 0.8)


def test_truncation_uses_the_configured_top_n(jev, make_state, monkeypatch):
    monkeypatch.setattr(settings, "rerank_top_n", 2)
    jev(scores=[0.9, 0.7, 0.5, 0.1])
    pool = [_ranked(2, 0.9), _ranked(4, 0.7), _ranked(3, 0.5), _ranked(1, 0.1)]

    out = rerank(make_state(pool=pool))

    assert [r.chunk_id for r in out["reranked"]] == [UUID(int=2), UUID(int=4)]


def _on_page(chunk_id: int, page: int, score: float) -> RankedChunk:
    return _ranked(chunk_id, score).model_copy(update={"article_id": UUID(int=page)})


def test_one_page_per_slot_gives_the_next_page_its_place(jev, make_state, monkeypatch):
    monkeypatch.setattr(settings, "rerank_top_n", 2)
    monkeypatch.setattr(settings, "rerank_top_n_per_page", 1)
    pool = [_on_page(1, 1, 0.9), _on_page(2, 1, 0.8), _on_page(3, 2, 0.7)]
    jev(scores=[0.9, 0.8, 0.7])

    out = rerank(make_state(pool=pool))["reranked"]

    assert [r.chunk_id for r in out] == [UUID(int=1), UUID(int=3)]


def test_the_per_page_limit_keeps_jevs_top_1_first(jev, make_state, monkeypatch):
    monkeypatch.setattr(settings, "rerank_top_n", 3)
    monkeypatch.setattr(settings, "rerank_top_n_per_page", 1)
    pool = [_on_page(1, 1, 0.5), _on_page(2, 2, 0.5), _on_page(3, 1, 0.5)]
    jev(scores=[0.2, 0.9, 0.8])

    out = rerank(make_state(pool=pool))["reranked"]

    assert out[0].chunk_id == UUID(int=2)
    assert [r.rerank_score for r in out] == sorted((r.rerank_score for r in out), reverse=True)


def test_a_per_page_limit_at_top_n_changes_nothing(jev, make_state, monkeypatch):
    monkeypatch.setattr(settings, "rerank_top_n", 3)
    monkeypatch.setattr(settings, "rerank_top_n_per_page", 3)
    pool = [_on_page(i, 1, 0.5) for i in (1, 2, 3, 4)]
    jev(scores=[0.9, 0.8, 0.7, 0.6])

    out = rerank(make_state(pool=pool))["reranked"]

    assert [r.chunk_id for r in out] == [UUID(int=1), UUID(int=2), UUID(int=3)]
