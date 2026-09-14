"""
Graph definition — spec §6.2, reproduced structurally as given. Three
properties are load-bearing and must survive any future edit to this
file:

1. No node writes to any business database. Every node either reads
   (KB/few-shot, via the read-only `ai_engine_ro` role — ADR-0004) or
   computes. The graph's only output is `signals` + `proposal`; core-api
   makes every decision downstream of that.
2. Refuse-before-LLM: if `rerank`'s top score is below `retrieval_floor`,
   the graph routes straight to `emit_signals` and `infer` is never
   reached — the single biggest cost/safety lever in the pipeline.
3. Exactly one loopable edge (`validate -> infer`), hard-capped at
   `iteration < 2`. There is no path through this graph that can loop
   more than once, structurally — not by convention.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, StateGraph

from ai_engine.config import Settings, settings
from ai_engine.graph.base import GraphNode
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import llm_infer
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode
from ai_engine.graph.state import TriageState
from ai_engine.providers.factory import Providers, build_providers


def _after_injection(state: TriageState) -> str:
    return "emit_signals" if state["injection"]["detected"] else "retrieve"


def _after_rerank(state: TriageState) -> str:
    reranked = state.get("reranked") or []
    if not reranked or reranked[0].score < state["retrieval_floor"]:
        return "emit_signals"
    return "select_shots"


def _after_validate(state: TriageState) -> str:
    validation = state.get("validation") or {}
    if not validation.get("schema_valid", False) and state["iteration"] < 2:
        return "infer"
    return "emit_signals"


@dataclass(frozen=True)
class GraphDeps:
    """The seven nodes, already configured.

    Separate from `Providers` so a test can swap ONE node without restating
    the other six, and so `build_graph` stays pure wiring. Fields are typed
    `GraphNode`, which a plain function satisfies as readily as a callable
    instance — that is what lets the function-to-class migration land one
    node at a time instead of all seven at once.
    """

    detect_inject: GraphNode
    retrieve: GraphNode
    rerank: GraphNode
    select_shots: GraphNode
    infer: GraphNode
    validate: GraphNode
    emit_signals: GraphNode

    @classmethod
    def from_settings(
        cls, s: Settings = settings, providers: Providers | None = None
    ) -> "GraphDeps":
        p = providers if providers is not None else build_providers(s)
        return cls(
            detect_inject=InjectionNode(),
            retrieve=HybridRetrieveNode(
                db=p.db,
                embedder=p.embedder,
                bm25_top_k=s.bm25_top_k,
                vector_top_k=s.vector_top_k,
                rrf_k=s.rrf_k,
                candidate_limit=s.fusion_candidate_limit,
            ),
            rerank=RerankNode(reranker=p.reranker, top_n=s.rerank_top_n),
            select_shots=SelectFewshotsNode(
                db=p.db, embedder=p.embedder, fewshot_k=s.fewshot_k
            ),
            infer=llm_infer,
            validate=ValidateNode(fuzzy_threshold=s.quote_fuzzy_threshold),
            emit_signals=EmitSignalsNode(db=p.db),
        )


def build_graph(deps: GraphDeps | None = None):
    deps = deps if deps is not None else GraphDeps.from_settings()

    g = StateGraph(TriageState)

    g.add_node("detect_inject", deps.detect_inject)
    g.add_node("retrieve", deps.retrieve)
    g.add_node("rerank", deps.rerank)
    g.add_node("select_shots", deps.select_shots)
    g.add_node("infer", deps.infer)
    g.add_node("validate", deps.validate)
    g.add_node("emit_signals", deps.emit_signals)

    g.set_entry_point("detect_inject")

    # Injection -> stop immediately, no further token spend.
    g.add_conditional_edges("detect_inject", _after_injection, ["emit_signals", "retrieve"])

    g.add_edge("retrieve", "rerank")

    # Retrieval floor -> refuse, LLM is NEVER called. Biggest cost saver:
    # a ticket with nothing relevant in the KB gives the model nothing to
    # do but fabricate an answer.
    g.add_conditional_edges("rerank", _after_rerank, ["emit_signals", "select_shots"])

    g.add_edge("select_shots", "infer")
    g.add_edge("infer", "validate")

    # Schema failure -> retry AT MOST once, then stop. Structurally
    # bounded by `iteration < 2` — cannot loop forever.
    g.add_conditional_edges("validate", _after_validate, ["infer", "emit_signals"])

    g.add_edge("emit_signals", END)

    return g.compile(checkpointer=None)  # stateless; idempotency lives at the Celery layer
