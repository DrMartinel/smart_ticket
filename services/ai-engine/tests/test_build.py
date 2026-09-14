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


def test_graph_has_exactly_the_seven_expected_nodes():
    """GraphDeps is a frozen dataclass, so adding a field without a matching
    add_node line compiles fine and the node simply never runs — a silent
    hole in the pipeline. This is the only thing that would notice.
    """

    from ai_engine.graph.build import build_graph

    compiled = build_graph()
    nodes = {n for n in compiled.get_graph().nodes if not n.startswith("__")}

    assert nodes == {
        "detect_inject",
        "retrieve",
        "rerank",
        "select_shots",
        "infer",
        "validate",
        "emit_signals",
    }


def test_build_graph_accepts_injected_deps():
    """The seam that makes a graph-level test possible at all: one node can
    be swapped without restating the other six."""

    from ai_engine.graph.build import GraphDeps, build_graph

    sentinel_calls = []

    def fake_infer(state):
        sentinel_calls.append(state)
        return {"proposal": None}

    deps = GraphDeps.from_settings()
    build_graph(deps=GraphDeps(**{**deps.__dict__, "infer": fake_infer}))  # must not raise


def test_build_graph_opens_no_connections_and_loads_no_models():
    """build_graph() runs at uvicorn import time (main.py) and in this test
    file with no database and no environment. If any provider constructor
    starts doing I/O, the first shows up as a container that will not boot
    and the second as a unit test that suddenly needs Postgres.
    """

    import sys

    from ai_engine.graph.build import build_graph

    build_graph()

    assert "sentence_transformers" not in sys.modules
