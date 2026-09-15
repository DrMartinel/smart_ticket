from ai_engine.config import settings
from ai_engine.retrieval.bm25 import LexicalHit
from ai_engine.retrieval.fusion import reciprocal_rank_fusion
from ai_engine.retrieval.vector import VectorHit


def test_rrf_favors_document_ranked_high_in_both_lists():
    bm25 = [
        LexicalHit(chunk_id=1, article_id=10, article_slug="KB-A", content="a", score=0.9),
        LexicalHit(chunk_id=2, article_id=11, article_slug="KB-B", content="b", score=0.5),
    ]
    vector = [
        VectorHit(chunk_id=1, article_id=10, article_slug="KB-A", content="a", score=0.8),
        VectorHit(chunk_id=3, article_id=12, article_slug="KB-C", content="c", score=0.7),
    ]
    fused = reciprocal_rank_fusion(bm25, vector)
    assert fused[0].chunk_id == 1  # rank 1 in both lists


def test_rrf_score_uses_standard_formula():
    bm25 = [LexicalHit(chunk_id=1, article_id=10, article_slug="KB-A", content="a", score=0.9)]
    vector = []
    fused = reciprocal_rank_fusion(bm25, vector)
    assert fused[0].rrf_score == 1.0 / (settings.rrf_k + 1)


def test_rrf_handles_disjoint_lists():
    bm25 = [LexicalHit(chunk_id=1, article_id=10, article_slug="KB-A", content="a", score=0.9)]
    vector = [VectorHit(chunk_id=2, article_id=11, article_slug="KB-B", content="b", score=0.9)]
    fused = reciprocal_rank_fusion(bm25, vector)
    assert {c.chunk_id for c in fused} == {1, 2}


def test_rrf_empty_inputs_return_empty():
    assert reciprocal_rank_fusion([], []) == []
