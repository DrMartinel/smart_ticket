"""
The whole triage topology — spec §6.2 — in one table. Nodes never know what
runs after them; `build.compile_graph` validates this table at startup
(every outcome routed, no dangling targets, nothing unreachable).

Three properties are load-bearing and must survive any future edit to this
table or the nodes:

1. No node writes to any business database. Every node either reads
   (KB/few-shot, via the read-only `ai_engine_ro` role — ADR-0004) or
   computes. The graph's only output is `signals` + `proposal`; core-api
   makes every decision downstream of that.
2. Refuse-before-LLM: if the reranker's top score is below
   `retrieval_floor`, the graph routes straight to `EmitSignalsNode` and
   `InferNode` is never reached — the single biggest cost/safety lever in
   the pipeline.
3. Exactly one loopable edge (`ValidateNode -> InferNode`), hard-capped at
   `iteration < 2`. There is no path through this graph that can loop
   more than once, structurally — not by convention.
"""

from __future__ import annotations

from ai_engine.graph.base import Flow, Terminal
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode

FLOW: Flow = {
    InjectionNode: {
        # Injection -> stop immediately, no further token spend.
        InjectionNode.Outcome.INJECTION_DETECTED: EmitSignalsNode,
        InjectionNode.Outcome.INJECTION_CLEAR: HybridRetrieveNode,
    },
    HybridRetrieveNode: {
        HybridRetrieveNode.Outcome.DONE: RerankNode,
    },
    RerankNode: {
        # Retrieval floor -> refuse, LLM is NEVER called. Biggest cost saver:
        # a ticket with nothing relevant in the KB gives the model nothing to
        # do but fabricate an answer.
        RerankNode.Outcome.EVIDENCE_BELOW_FLOOR: EmitSignalsNode,
        RerankNode.Outcome.EVIDENCE_ABOVE_FLOOR: SelectFewshotsNode,
    },
    SelectFewshotsNode: {
        SelectFewshotsNode.Outcome.DONE: InferNode,
    },
    InferNode: {
        InferNode.Outcome.DONE: ValidateNode,
    },
    ValidateNode: {
        # The graph's only cycle — bounded by `iteration < 2` in
        # ValidateNode.decide, so it cannot loop more than once.
        ValidateNode.Outcome.RETRY_INFERENCE: InferNode,
        ValidateNode.Outcome.SCHEMA_VALID: EmitSignalsNode,
        ValidateNode.Outcome.RETRIES_EXHAUSTED: EmitSignalsNode,
    },
    # Every path through the graph ends here.
    EmitSignalsNode: {
        EmitSignalsNode.Outcome.DONE: Terminal,
    },
}

ENTRY = InjectionNode
