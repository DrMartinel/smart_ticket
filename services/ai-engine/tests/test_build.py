"""
Graph routing tests — spec §6.2's two safety-critical structural
properties: refuse-before-LLM, and a retry loop hard-capped at
iteration < 2. Each node's `decide()` is tested directly, and the routes
those outcomes map to are pinned separately — together that is the whole
routing decision, with no DB/LLM/network involved.
"""

from ai_engine.core.node import Terminal
from ai_engine.core.state import ValidationResult
from ai_engine.graph.flow import wire_triage
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RankedChunk, RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode


def _chunk(score: float) -> RankedChunk:
    return RankedChunk(chunk_id=1, article_id=1, article_slug="KB-1", content="x", score=score)


def test_injection_detected_decides_detected(make_state):
    state = make_state(injection={"detected": True, "matched_patterns": ["x"]})
    assert InjectionNode().decide(state) is InjectionNode.Outcome.INJECTION_DETECTED


def test_no_injection_decides_clear(make_state):
    state = make_state(injection={"detected": False, "matched_patterns": []})
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
    validation = ValidationResult.all_failed().model_copy(update={"schema_valid": False})
    state = make_state(validation=validation, iteration=0)
    node = ValidateNode()
    assert node.decide(state) is ValidateNode.Outcome.RETRY_INFERENCE


def test_schema_invalid_stops_retrying_after_iteration_cap(make_state):
    validation = ValidationResult.all_failed().model_copy(update={"schema_valid": False})
    state = make_state(validation=validation, iteration=2)
    node = ValidateNode()
    assert node.decide(state) is ValidateNode.Outcome.RETRIES_EXHAUSTED


def test_schema_valid_decides_valid(make_state):
    validation = ValidationResult.all_failed().model_copy(update={"schema_valid": True})
    state = make_state(validation=validation, iteration=0)
    node = ValidateNode()
    assert node.decide(state) is ValidateNode.Outcome.SCHEMA_VALID


def test_safety_critical_routes(triage_nodes):
    """The outcomes above are only half the routing decision; these are the
    routes that make them mean refuse-before-LLM and a bounded retry."""

    n = triage_nodes()
    g = wire_triage(**n)

    assert g.entry is n["injection"]
    assert g.routes[n["injection"]][InjectionNode.Outcome.INJECTION_DETECTED] is n["emit"]
    assert g.routes[n["rerank"]][RerankNode.Outcome.EVIDENCE_BELOW_FLOOR] is n["emit"]
    assert g.routes[n["validate"]][ValidateNode.Outcome.RETRY_INFERENCE] is n["infer"]
    assert g.routes[n["validate"]][ValidateNode.Outcome.RETRIES_EXHAUSTED] is n["emit"]
    assert isinstance(g.routes[n["emit"]][EmitSignalsNode.Outcome.DONE], Terminal)


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


def test_compiled_edges_match_wiring(triage_nodes):
    """The production topology is asserted rather than eyeballed: every
    route declared in wire_triage is an edge, and there are no edges it does
    not declare."""

    from ai_engine.main import _graph

    edges = {(e.source, e.target) for e in _graph.get_graph().edges}

    g = wire_triage(**triage_nodes())
    expected = {("__start__", g.entry.name), (Terminal.name, "__end__")}
    for source, routes in g.routes.items():
        for target in routes.values():
            expected.add((source.name, target.name))

    assert edges == expected


def test_main_wires_the_prompt_for_settings_prompt_version():
    """The prompt filename used to be hardcoded, so bumping
    settings.prompt_version changed what the response *claimed* ran without
    changing what actually ran. This reads the prompt off the InferNode in
    the production graph."""

    from ai_engine.core.config import settings
    from ai_engine.llm.prompt_store import load_system_prompt
    from ai_engine.main import _graph

    # LangGraph internals: PregelNode.bound is the RunnableCallable wrapping
    # the node instance we registered.
    infer = _graph.nodes[InferNode.name].bound.func

    expected = load_system_prompt(settings.prompt_version)
    assert infer._system_prompt == expected
    assert expected.strip() != ""
