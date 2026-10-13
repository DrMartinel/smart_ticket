from uuid import UUID

from ai_engine.graph.nodes.retrieve.bm25 import LexicalHit
from ai_engine.graph.nodes.retrieve.fusion import reciprocal_rank_fusion
from ai_engine.graph.nodes.retrieve.vector import VectorHit


def _lexical(chunk: int) -> LexicalHit:
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


def test_rrf_favors_a_chunk_ranked_high_in_two_lists():
    fused = reciprocal_rank_fusion([[_lexical(1), _lexical(2)], [_vector(1), _vector(3)]])

    assert fused[0].chunk_id == UUID(int=1)  # rank 1 in both lists


def test_rrf_handles_disjoint_lists():
    fused = reciprocal_rank_fusion([[_lexical(1)], [_vector(2)]])

    assert {c.chunk_id for c in fused} == {UUID(int=1), UUID(int=2)}


def test_one_list_keeps_its_own_order():
    fused = reciprocal_rank_fusion([[_vector(3), _vector(1), _vector(2)]])

    assert [c.chunk_id for c in fused] == [UUID(int=3), UUID(int=1), UUID(int=2)]


def test_rrf_empty_inputs_return_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
