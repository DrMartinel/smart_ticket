"""
The budget guard's contract. The per-node degrade tests (test_retrieve,
test_rerank, test_infer) prove each real node spends nothing when over
budget; these pin the base class those guarantees rest on, and prove the
degrade still reaches a human through the compiled graph.
"""

import pytest

from ai_engine.graph.budget import BudgetedNode

_LIMITS = pytest.mark.parametrize(
    "overrides",
    [
        {"iteration": 5, "max_graph_iterations": 5},
        {"llm_calls": 1, "max_llm_calls": 1},
        {"tokens_used": 100, "max_tokens": 100},
        {"started_at": 0.0, "max_latency_sec": 1},
    ],
    ids=["iterations", "llm_calls", "tokens", "latency"],
)


class _SpyNode(BudgetedNode):
    def __init__(self):
        self.ran = []

    def __call__(self, state: dict) -> dict:
        self.ran.append(state)  # test-only spy; real nodes never write to self
        return {"candidates": ["work"]}


def test_within_budget_runs_the_node(make_state):
    node = _SpyNode()

    assert node(make_state()) == {"candidates": ["work"]}
    assert len(node.ran) == 1


@_LIMITS
def test_over_budget_returns_only_degraded_reason_without_running(make_state, overrides):
    node = _SpyNode()

    assert node(make_state(**overrides)) == {"degraded_reason": "budget_exceeded"}
    assert node.ran == []


def test_a_subclass_overriding_call_again_is_still_guarded(make_state, exhausted_budget_state):
    """A test fake that subclasses a real node and replaces __call__ must not
    be a way around the budget — its override is wrapped too."""

    class _FakeSpyNode(_SpyNode):
        def __call__(self, state: dict) -> dict:
            self.ran.append(state)
            return {"candidates": ["fake"]}

    node = _FakeSpyNode()

    assert node(exhausted_budget_state()) == {"degraded_reason": "budget_exceeded"}
    assert node.ran == []
    assert node(make_state()) == {"candidates": ["fake"]}


def test_wrapped_call_keeps_the_node_signature():
    """LangGraph reads __call__'s type hints when a node is registered, and
    tracebacks should name the node's own method."""

    from ai_engine.graph.nodes.rerank import RerankNode

    call = RerankNode.__call__
    assert call.__qualname__ == "RerankNode.__call__"
    assert call.__annotations__ == call.__wrapped__.__annotations__


def test_over_budget_ticket_still_reaches_emit_signals_through_the_graph(
    fake_embedder, fake_reranker, fake_llm, triage_nodes, exhausted_budget_state
):
    """The nodes' own output keys are absent when degraded. This proves that
    is enough: the compiled graph still routes to emit_signals, produces
    TrustSignals, and never touches the embedder, reranker or LLM — rather
    than a BudgetExceeded escaping and aborting the run."""

    from ai_engine.graph.build import compile_graph
    from ai_engine.graph.flow import ENTRY, FLOW
    from ai_engine.graph.state import TriageState

    embedder, reranker, llm = fake_embedder(), fake_reranker(), fake_llm()
    nodes = triage_nodes(embedder=embedder, reranker=reranker, llm=llm)
    graph = compile_graph(TriageState, nodes, FLOW, ENTRY)

    final = graph.invoke(exhausted_budget_state())

    assert final["degraded_reason"] == "budget_exceeded"
    assert final["signals"].retrieval.rerank_top1 == 0.0
    assert final.get("proposal") is None
    assert embedder.calls == [] and reranker.calls == [] and llm.prompts == []
