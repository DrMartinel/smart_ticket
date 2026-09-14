"""
Graph routing tests — spec §6.2's two safety-critical structural
properties: refuse-before-LLM, and a retry loop hard-capped at
iteration < 2. Each node's `decide()` is tested directly, and the FLOW rows
those outcomes map to are pinned separately — together that is the whole
routing decision, with no DB/LLM/network involved.
"""

from ai_engine.graph.base import Terminal
from ai_engine.graph.flow import ENTRY, FLOW
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RankedChunk, RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode


def _chunk(score: float) -> RankedChunk:
    return RankedChunk(chunk_id=1, article_id=1, article_slug="KB-1", content="x", score=score)


def test_injection_detected_decides_detected():
    state = {"injection": {"detected": True, "matched_patterns": ["x"]}}
    assert InjectionNode().decide(state) is InjectionNode.Outcome.INJECTION_DETECTED


def test_no_injection_decides_clear():
    state = {"injection": {"detected": False, "matched_patterns": []}}
    assert InjectionNode().decide(state) is InjectionNode.Outcome.INJECTION_CLEAR


def test_empty_reranked_is_below_floor(fake_reranker):
    state = {"reranked": [], "retrieval_floor": 0.45}
    node = RerankNode(reranker=fake_reranker(), top_n=3)
    assert node.decide(state) is RerankNode.Outcome.EVIDENCE_BELOW_FLOOR


def test_below_floor_is_below_floor(fake_reranker):
    state = {"reranked": [_chunk(0.1)], "retrieval_floor": 0.45}
    node = RerankNode(reranker=fake_reranker(), top_n=3)
    assert node.decide(state) is RerankNode.Outcome.EVIDENCE_BELOW_FLOOR


def test_above_floor_is_above_floor(fake_reranker):
    state = {"reranked": [_chunk(0.9)], "retrieval_floor": 0.45}
    node = RerankNode(reranker=fake_reranker(), top_n=3)
    assert node.decide(state) is RerankNode.Outcome.EVIDENCE_ABOVE_FLOOR


def test_schema_invalid_retries_once(fuzzy_threshold):
    state = {"validation": {"schema_valid": False}, "iteration": 0}
    node = ValidateNode(fuzzy_threshold=fuzzy_threshold)
    assert node.decide(state) is ValidateNode.Outcome.RETRY_INFERENCE


def test_schema_invalid_stops_retrying_after_iteration_cap(fuzzy_threshold):
    state = {"validation": {"schema_valid": False}, "iteration": 2}
    node = ValidateNode(fuzzy_threshold=fuzzy_threshold)
    assert node.decide(state) is ValidateNode.Outcome.RETRIES_EXHAUSTED


def test_schema_valid_decides_valid(fuzzy_threshold):
    state = {"validation": {"schema_valid": True}, "iteration": 0}
    node = ValidateNode(fuzzy_threshold=fuzzy_threshold)
    assert node.decide(state) is ValidateNode.Outcome.SCHEMA_VALID


def test_safety_critical_flow_rows():
    """The outcomes above are only half the routing decision; these are the
    rows that make them mean refuse-before-LLM and a bounded retry."""

    assert ENTRY is InjectionNode
    assert FLOW[InjectionNode][InjectionNode.Outcome.INJECTION_DETECTED] is EmitSignalsNode
    assert FLOW[RerankNode][RerankNode.Outcome.EVIDENCE_BELOW_FLOOR] is EmitSignalsNode
    assert FLOW[ValidateNode][ValidateNode.Outcome.RETRY_INFERENCE] is InferNode
    assert FLOW[ValidateNode][ValidateNode.Outcome.RETRIES_EXHAUSTED] is EmitSignalsNode
    assert FLOW[EmitSignalsNode][EmitSignalsNode.Outcome.DONE] is Terminal


def test_graph_has_exactly_the_seven_expected_nodes():
    from ai_engine.main import _graph

    nodes = {n for n in _graph.get_graph().nodes if not n.startswith("__")}

    assert nodes == {
        InjectionNode.name,
        HybridRetrieveNode.name,
        RerankNode.name,
        SelectFewshotsNode.name,
        InferNode.name,
        ValidateNode.name,
        EmitSignalsNode.name,
    }
    # Pinned literally once: these strings are what shows up in traces.
    assert nodes == {
        "injection",
        "hybrid_retrieve",
        "rerank",
        "select_fewshots",
        "infer",
        "validate",
        "emit_signals",
    }


def test_compiled_edges_match_flow():
    """The production topology is asserted rather than eyeballed: every FLOW
    row is an edge, and there are no edges FLOW does not declare."""

    from ai_engine.main import _graph

    edges = {(e.source, e.target) for e in _graph.get_graph().edges}

    expected = {("__start__", ENTRY.name)}
    for cls, routes in FLOW.items():
        for target in routes.values():
            expected.add((cls.name, "__end__" if target is Terminal else target.name))

    assert edges == expected


def test_graph_accepts_an_injected_node(triage_nodes):
    """The seam that makes a graph-level test possible at all: one node can
    be swapped for a subclass without restating the other six."""

    from ai_engine.graph.build import compile_graph
    from ai_engine.graph.state import TriageState

    class FakeInferNode(InferNode):
        def __init__(self):
            pass

        def __call__(self, state):
            return {"proposal": None}

    nodes = [FakeInferNode() if isinstance(n, InferNode) else n for n in triage_nodes()]
    compiled = compile_graph(TriageState, nodes, FLOW, ENTRY)  # must not raise

    assert InferNode.name in compiled.get_graph().nodes


def test_importing_main_opens_no_connections_and_loads_no_models():
    """main.py builds the graph at uvicorn import time, and this test file
    imports it with no database and no environment. If any provider
    constructor starts doing I/O, the first shows up as a container that
    will not boot and the second as a unit test that suddenly needs Postgres.
    """

    import sys

    import ai_engine.main  # noqa: F401

    assert "sentence_transformers" not in sys.modules
