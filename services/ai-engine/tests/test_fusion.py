from uuid import UUID

from ai_engine.core.config import settings
from ai_engine.graph.nodes.retrieve.bm25 import LexicalHit
from ai_engine.graph.nodes.retrieve.fusion import reciprocal_rank_fusion
from ai_engine.graph.nodes.retrieve.vector import VectorHit


def test_rrf_favors_document_ranked_high_in_both_lists():
    bm25 = [
        LexicalHit(
            chunk_id=UUID(int=1),
            article_id=UUID(int=10),
            article_slug="KB-A",
            content="a",
            score=0.9,
        ),
        LexicalHit(
            chunk_id=UUID(int=2),
            article_id=UUID(int=11),
            article_slug="KB-B",
            content="b",
            score=0.5,
        ),
    ]
    vector = [
        VectorHit(
            chunk_id=UUID(int=1),
            article_id=UUID(int=10),
            article_slug="KB-A",
            content="a",
            score=0.8,
        ),
        VectorHit(
            chunk_id=UUID(int=3),
            article_id=UUID(int=12),
            article_slug="KB-C",
            content="c",
            score=0.7,
        ),
    ]
    fused = reciprocal_rank_fusion(bm25, vector)
    assert fused[0].chunk_id == UUID(int=1)  # rank 1 in both lists


def test_rrf_handles_disjoint_lists():
    bm25 = [
        LexicalHit(
            chunk_id=UUID(int=1),
            article_id=UUID(int=10),
            article_slug="KB-A",
            content="a",
            score=0.9,
        )
    ]
    vector = [
        VectorHit(
            chunk_id=UUID(int=2),
            article_id=UUID(int=11),
            article_slug="KB-B",
            content="b",
            score=0.9,
        )
    ]
    fused = reciprocal_rank_fusion(bm25, vector)
    assert {c.chunk_id for c in fused} == {UUID(int=1), UUID(int=2)}


def test_rrf_empty_inputs_return_empty():
    assert reciprocal_rank_fusion([], []) == []


def _bm25(chunk: int) -> LexicalHit:
    return LexicalHit(
        chunk_id=UUID(int=chunk),
        article_id=UUID(int=chunk * 10),
        article_slug=f"KB-{chunk}",
        content="x",
        score=1.0,
    )


def _vector(chunk: int) -> VectorHit:
    return VectorHit(
        chunk_id=UUID(int=chunk),
        article_id=UUID(int=chunk * 10),
        article_slug=f"KB-{chunk}",
        content="x",
        score=0.5,
    )


def test_a_weight_of_one_is_plain_rrf(monkeypatch):
    """The weight at 1 must reproduce unweighted RRF exactly: chunk 1, BM25's
    first, ties chunk 2, vector's first, and both lists' first order keeps."""

    monkeypatch.setattr(settings, "rrf_bm25_weight", 1.0)
    fused = reciprocal_rank_fusion([_bm25(1), _bm25(3)], [_vector(2), _vector(3)])

    # Chunk 3 is in both lists (2nd in each): 2 / (k + 2) beats 1 / (k + 1).
    assert [c.chunk_id for c in fused] == [UUID(int=3), UUID(int=1), UUID(int=2)]


def test_a_low_bm25_weight_never_puts_a_bm25_only_chunk_above_a_vector_hit(monkeypatch):
    """The point of down-weighting BM25 (2026-10-11): a chunk only keyword
    matching found must not outrank one the embedding found, even BM25's
    first against vector's last. BM25 then only reorders agreed chunks."""

    monkeypatch.setattr(settings, "rrf_bm25_weight", 0.5)
    vector = [_vector(i) for i in range(2, 22)]  # 20 hits, as vector_top_k
    fused = reciprocal_rank_fusion([_bm25(1)], vector)

    assert fused[-1].chunk_id == UUID(int=1)


def test_bm25_still_breaks_ties_between_vector_hits_at_a_low_weight(monkeypatch):
    """Down-weighted, not removed: a vector hit BM25 also found moves above
    one it didn't."""

    monkeypatch.setattr(settings, "rrf_bm25_weight", 0.5)
    fused = reciprocal_rank_fusion([_bm25(3)], [_vector(2), _vector(3)])

    assert [c.chunk_id for c in fused][:2] == [UUID(int=3), UUID(int=2)]
