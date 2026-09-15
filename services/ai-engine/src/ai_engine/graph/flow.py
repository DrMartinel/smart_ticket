"""
The whole triage topology — spec §6.2 — in one function. Nodes never know
what runs after them; `GraphBuilder.compile` validates these routes at
startup (every outcome routed, nothing unreachable, a Terminal reachable).

`main.py` and the tests' `triage_nodes` fixture both wire through
`wire_triage`, and every node is a required keyword, so production and test
topology cannot drift apart.

Three properties are load-bearing and must survive any future edit to this
function or the nodes:

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

from ai_engine.core.node import Terminal
from ai_engine.graph.build import GraphBuilder
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode


def wire_triage(
    *,
    injection: InjectionNode,
    retrieve: HybridRetrieveNode,
    rerank: RerankNode,
    fewshots: SelectFewshotsNode,
    infer: InferNode,
    validate: ValidateNode,
    emit: EmitSignalsNode,
) -> GraphBuilder:
    g = GraphBuilder(entry=injection)

    g.route(injection, InjectionNode.Outcome.INJECTION_DETECTED, emit)
    g.route(injection, InjectionNode.Outcome.INJECTION_CLEAR, retrieve)

    g.route(retrieve, HybridRetrieveNode.Outcome.DONE, rerank)

    g.route(rerank, RerankNode.Outcome.EVIDENCE_BELOW_FLOOR, emit)
    g.route(rerank, RerankNode.Outcome.EVIDENCE_ABOVE_FLOOR, fewshots)

    g.route(fewshots, SelectFewshotsNode.Outcome.DONE, infer)
    g.route(infer, InferNode.Outcome.DONE, validate)

    # The graph's only cycle — bounded by `iteration < 2` in
    # ValidateNode.decide, so it cannot loop more than once.
    g.route(validate, ValidateNode.Outcome.RETRY_INFERENCE, infer)
    g.route(validate, ValidateNode.Outcome.SCHEMA_VALID, emit)
    g.route(validate, ValidateNode.Outcome.RETRIES_EXHAUSTED, emit)

    # Every path through the graph ends here. Terminal has no collaborators,
    # so it is built here rather than passed in.
    g.route(emit, EmitSignalsNode.Outcome.DONE, Terminal())

    return g
