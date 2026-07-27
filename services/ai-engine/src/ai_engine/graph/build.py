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

from langgraph.graph import END, StateGraph

from ai_engine.graph.nodes.emit_signals import build_trust_signals
from ai_engine.graph.nodes.fewshot import select_fewshots
from ai_engine.graph.nodes.infer import llm_infer
from ai_engine.graph.nodes.injection import detect_injection
from ai_engine.graph.nodes.rerank import cross_encoder_rerank
from ai_engine.graph.nodes.retrieve import hybrid_retrieve
from ai_engine.graph.nodes.validate import validate_output
from ai_engine.graph.state import TriageState


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


def build_graph():
    g = StateGraph(TriageState)

    g.add_node("detect_inject", detect_injection)
    g.add_node("retrieve", hybrid_retrieve)
    g.add_node("rerank", cross_encoder_rerank)
    g.add_node("select_shots", select_fewshots)
    g.add_node("infer", llm_infer)
    g.add_node("validate", validate_output)
    g.add_node("emit_signals", build_trust_signals)

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
