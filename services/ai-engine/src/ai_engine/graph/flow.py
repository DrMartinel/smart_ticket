"""
The whole triage topology — spec §6.2. `GraphBuilder.compile` validates it at
startup; `main.py` and the tests' `triage_nodes` fixture both wire through
`wire_triage`, so they cannot drift.

Load-bearing properties:

1. No node writes to a business database. Nodes only read (via `ai_engine_ro`,
   ADR-0004) or compute; core-api makes every decision.
2. Refuse-before-LLM: a top rerank score below `retrieval_floor` routes
   straight to `EmitSignalsNode`, never reaching `InferNode`.
3. Exactly one loopable edge (`ValidateNode -> InferNode`), capped at
   `iteration < 2`, so no run can loop more than once — structurally.
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
