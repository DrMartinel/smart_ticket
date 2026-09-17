"""
Graph routing — spec §6.2's refuse-before-LLM and a retry loop capped at
iteration < 2. Each node's `decide()` and the routes its outcomes map to are
tested separately, with no DB, LLM or network.
"""

from ai_engine.core.node import Terminal
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.core.retrieval.rerank import RankedChunk
from ai_engine.graph.nodes.rerank import RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode


def _chunk(score: float) -> RankedChunk:
    return RankedChunk(chunk_id=1, article_id=1, article_slug="KB-1", content="x", score=score)


def test_injection_detected_decides_detected(make_state):
    state = make_state(injection_detected=True)
    assert InjectionNode().decide(state) is InjectionNode.Outcome.INJECTION_DETECTED


def test_no_injection_decides_clear(make_state):
    state = make_state(injection_detected=False)
    assert InjectionNode().decide(state) is InjectionNode.Outcome.INJECTION_CLEAR


def test_empty_reranked_is_below_floor(fake_reranker, make_state):
    state = make_state(reranked=[], retrieval_floor=0.45)
    node = RerankNode(reranker=fake_reranker())
    assert node.decide(state) is RerankNode.Outcome.EVIDENCE_BELOW_FLOOR


def test_below_floor_is_below_floor(fake_reranker, make_state):
    state = make_state(reranked=[_chunk(0.1)], retrieval_floor=0.45)
    node = RerankNode(reranker=fake_reranker())
    assert node.decide(state) is RerankNode.Outcome.EVIDENCE_BELOW_FLOOR


def test_above_floor_is_above_floor(fake_reranker, make_state):
    state = make_state(reranked=[_chunk(0.9)], retrieval_floor=0.45)
    node = RerankNode(reranker=fake_reranker())
    assert node.decide(state) is RerankNode.Outcome.EVIDENCE_ABOVE_FLOOR


def test_schema_invalid_retries_once(make_state):
    state = make_state(schema_valid=False, iteration=0)
    node = ValidateNode()
    assert node.decide(state) is ValidateNode.Outcome.RETRY_INFERENCE


def test_schema_invalid_stops_retrying_after_iteration_cap(make_state):
    state = make_state(schema_valid=False, iteration=2)
    node = ValidateNode()
    assert node.decide(state) is ValidateNode.Outcome.RETRIES_EXHAUSTED


def test_schema_valid_decides_valid(make_state):
    state = make_state(schema_valid=True, iteration=0)
    node = ValidateNode()
    assert node.decide(state) is ValidateNode.Outcome.SCHEMA_VALID


def _edges() -> dict[tuple[str, str], str | None]:
    """The production graph's edges as (source, target) -> outcome label.
    Unconditional edges have no label."""

    from ai_engine.main import _graph

    return {(e.source, e.target): e.data for e in _graph.get_graph().edges}


def test_safety_critical_routes():
    """The outcomes above are only half the routing decision; these are the
    routes that make them mean refuse-before-LLM and a bounded retry."""

    edges = _edges()

    assert ("__start__", "injection") in edges
    assert edges[("injection", "emit_signals")] == InjectionNode.Outcome.INJECTION_DETECTED
    assert edges[("rerank", "emit_signals")] == RerankNode.Outcome.EVIDENCE_BELOW_FLOOR
    assert edges[("validate", "infer")] == ValidateNode.Outcome.RETRY_INFERENCE
    # SCHEMA_VALID and RETRIES_EXHAUSTED share this edge, so it carries only
    # one label; that both outcomes are routed is enforced by compile().
    assert ("validate", "emit_signals") in edges
    assert ("emit_signals", "terminal") in edges


def test_graph_has_exactly_the_expected_nodes():
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
        Terminal.name,
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
        "terminal",
    }


def test_compiled_edges_are_exactly_the_triage_topology():
    """Pins the production topology literally: an added, dropped or
    redirected route fails. Refuse-before-LLM is the absence of a rerank →
    infer path that skips select_fewshots.
    """

    assert set(_edges()) == {
        ("__start__", "injection"),
        ("injection", "emit_signals"),
        ("injection", "hybrid_retrieve"),
        ("hybrid_retrieve", "rerank"),
        ("rerank", "emit_signals"),
        ("rerank", "select_fewshots"),
        ("select_fewshots", "infer"),
        ("infer", "validate"),
        ("validate", "infer"),
        ("validate", "emit_signals"),
        ("emit_signals", "terminal"),
        ("terminal", "__end__"),
    }


def test_main_wires_the_prompt_for_settings_prompt_version():
    """Bumping settings.prompt_version must change the prompt that actually
    runs, not just the version reported. Reads the prompt off the
    production InferNode.
    """

    from ai_engine.core.config import settings
    from ai_engine.core.prompts import load_system_prompt
    from ai_engine.main import _graph

    # LangGraph internals: PregelNode.bound is the RunnableCallable wrapping
    # GraphBuilder's adapter, which keeps the node instance on `.node`.
    infer = _graph.nodes[InferNode.name].bound.func.node

    expected = load_system_prompt(settings.prompt_version)
    assert infer._system_prompt == expected
    assert expected.strip() != ""
