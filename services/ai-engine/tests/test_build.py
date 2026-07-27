"""
Graph routing-function tests — spec §6.2's two safety-critical structural
properties: refuse-before-LLM, and a retry loop hard-capped at
iteration < 2. Testing the conditional-edge functions directly (rather
than running the whole compiled graph) keeps these fast and independent
of any DB/LLM/network — the same reasoning as router.py's own tests.
"""

from ai_engine.graph.build import _after_injection, _after_rerank, _after_validate
from ai_engine.graph.nodes.rerank import RankedChunk


def test_injection_detected_skips_straight_to_emit_signals():
    state = {"injection": {"detected": True, "matched_patterns": ["x"]}}
    assert _after_injection(state) == "emit_signals"


def test_no_injection_proceeds_to_retrieve():
    state = {"injection": {"detected": False, "matched_patterns": []}}
    assert _after_injection(state) == "retrieve"


def test_empty_reranked_refuses_before_llm():
    state = {"reranked": [], "retrieval_floor": 0.45}
    assert _after_rerank(state) == "emit_signals"


def test_below_floor_refuses_before_llm():
    state = {
        "reranked": [RankedChunk(chunk_id=1, article_id=1, article_slug="KB-1", content="x", score=0.1)],
        "retrieval_floor": 0.45,
    }
    assert _after_rerank(state) == "emit_signals"


def test_above_floor_proceeds_to_select_shots():
    state = {
        "reranked": [RankedChunk(chunk_id=1, article_id=1, article_slug="KB-1", content="x", score=0.9)],
        "retrieval_floor": 0.45,
    }
    assert _after_rerank(state) == "select_shots"


def test_schema_invalid_retries_once():
    state = {"validation": {"schema_valid": False}, "iteration": 0}
    assert _after_validate(state) == "infer"


def test_schema_invalid_stops_retrying_after_iteration_cap():
    state = {"validation": {"schema_valid": False}, "iteration": 2}
    assert _after_validate(state) == "emit_signals"


def test_schema_valid_goes_straight_to_emit_signals():
    state = {"validation": {"schema_valid": True}, "iteration": 0}
    assert _after_validate(state) == "emit_signals"


def test_graph_compiles():
    from ai_engine.graph.build import build_graph

    build_graph()  # must not raise
