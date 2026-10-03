from uuid import UUID
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
