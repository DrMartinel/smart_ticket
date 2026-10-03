"""
Graph routing — spec §6.2's refuse-before-LLM, in an acyclic graph. Each node's `decide()` and the routes its outcomes map to are
tested separately, with no DB, LLM or network.
"""

from uuid import UUID

from ai_engine.graph.build.node import Terminal
from ai_engine.graph.nodes.candidate_pool.node import CandidatePoolNode
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode, InjectionOutcome, injection
from ai_engine.graph.state import RankedChunk
from ai_engine.graph.nodes.rerank.node import RerankNode, RerankOutcome, rerank
from ai_engine.graph.nodes.retrieve.node import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode


def _chunk(score: float) -> RankedChunk:
    return RankedChunk(
        chunk_id=UUID(int=1),
        article_id=UUID(int=1),
        article_slug="KB-1",
        content="x",
        shortlist_score=score,
        rerank_score=score,
    )


def test_injection_detected_decides_detected(make_state):
    state = make_state(injection_detected=True)
    assert injection.decide(state) is InjectionOutcome.INJECTION_DETECTED


def test_no_injection_decides_clear(make_state):
    state = make_state(injection_detected=False)
    assert injection.decide(state) is InjectionOutcome.INJECTION_CLEAR


def test_empty_reranked_is_below_floor(make_state):
    state = make_state(reranked=[], retrieval_floor=0.45)
    node = rerank
    assert node.decide(state) is RerankOutcome.EVIDENCE_BELOW_FLOOR


def test_below_floor_is_below_floor(make_state):
    state = make_state(reranked=[_chunk(0.1)], retrieval_floor=0.45)
    node = rerank
    assert node.decide(state) is RerankOutcome.EVIDENCE_BELOW_FLOOR


def test_above_floor_is_above_floor(make_state):
    state = make_state(reranked=[_chunk(0.9)], retrieval_floor=0.45)
    node = rerank
    assert node.decide(state) is RerankOutcome.EVIDENCE_ABOVE_FLOOR


def test_decide_reads_the_jev_score_not_the_cross_encoders(make_state):
    """ADR-0005/0015: a chunk the cross-encoder liked (0.9) but Jev didn't
    (0.1) is below a 0.30 Jev floor. Reading the cross-encoder field would
    send it to the LLM as evidence."""

    chunk = _chunk(0.9).model_copy(update={"rerank_score": 0.1})
    state = make_state(reranked=[chunk], retrieval_floor=0.30)

    assert rerank.decide(state) is RerankOutcome.EVIDENCE_BELOW_FLOOR


def _edges() -> dict[tuple[str, str], object]:
    """The production graph's edges as (source, target) -> outcome label.
    Unconditional edges have no label."""

    from ai_engine.graph.triage import triage_graph

    return {(e.source, e.target): e.data for e in triage_graph.get_graph().edges}


def test_safety_critical_routes():
    """The outcomes above are only half the routing decision; these are the
    routes that make them mean refuse-before-LLM, and a schema failure goes
    to a human rather than back to the model."""

    edges = _edges()

    assert ("__start__", "injection") in edges
    assert edges[("injection", "emit_signals")] == InjectionOutcome.INJECTION_DETECTED
    assert edges[("rerank", "emit_signals")] == RerankOutcome.EVIDENCE_BELOW_FLOOR
    # Expansion feeds the floor's node; nothing skips it to reach the LLM.
    assert ("candidate_pool", "rerank") in edges
    assert ("candidate_pool", "select_fewshots") not in edges
    assert ("validate", "infer") not in edges
    assert ("validate", "emit_signals") in edges
    assert ("emit_signals", "terminal") in edges


def test_graph_has_exactly_the_expected_nodes():
    from ai_engine.graph.triage import triage_graph

    nodes = {n for n in triage_graph.get_graph().nodes if not n.startswith("__")}

    assert nodes == {
        InjectionNode.name,
        HybridRetrieveNode.name,
        CandidatePoolNode.name,
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
        "candidate_pool",
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
        ("hybrid_retrieve", "candidate_pool"),
        ("candidate_pool", "rerank"),
        ("rerank", "emit_signals"),
        ("rerank", "select_fewshots"),
        ("select_fewshots", "infer"),
        ("infer", "validate"),
        ("validate", "emit_signals"),
        ("emit_signals", "terminal"),
        ("terminal", "__end__"),
    }


def test_the_classify_prompt_is_the_file_settings_prompt_version_names():
    """Bumping settings.prompt_version must change the prompt that actually
    runs, not just the version reported. InferNode sends CLASSIFY_PROMPT
    (test_infer.py pins that)."""

    from ai_engine.core.config import settings
    from ai_engine.core.prompts import CLASSIFY_PROMPT, PROMPT_DIR

    expected = (PROMPT_DIR / f"{settings.prompt_version}.md").read_text()
    assert CLASSIFY_PROMPT == expected
    assert expected.strip() != ""
