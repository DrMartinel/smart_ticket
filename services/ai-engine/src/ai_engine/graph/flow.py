"""
The whole triage topology — spec §6.2. `GraphBuilder.compile` validates it at
startup; `main.py` and the tests' `triage_nodes` fixture both wire through
`wire_triage`, so they cannot drift.

Load-bearing properties:

1. No node writes to a business database. Nodes only read (via `ai_engine_ro`,
   ADR-0004) or compute; core-api makes every decision.
2. Refuse-before-LLM: a top rerank score below `retrieval_floor` routes
   straight to `EmitSignalsNode`, never reaching `InferNode`.
3. The graph is acyclic: every node runs at most once per ticket. A proposal
   that fails schema validation goes to a human, not back to the model.
"""

from __future__ import annotations

from ai_engine.core.node import SingleExit, Terminal
from ai_engine.graph.build import GraphBuilder
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode, InjectionOutcome
from ai_engine.graph.nodes.rerank import RerankNode, RerankOutcome
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

    g.route(injection, InjectionOutcome.INJECTION_DETECTED, emit)
    g.route(injection, InjectionOutcome.INJECTION_CLEAR, retrieve)

    g.route(retrieve, SingleExit.DONE, rerank)

    g.route(rerank, RerankOutcome.EVIDENCE_BELOW_FLOOR, emit)
    g.route(rerank, RerankOutcome.EVIDENCE_ABOVE_FLOOR, fewshots)

    g.route(fewshots, SingleExit.DONE, infer)
    g.route(infer, SingleExit.DONE, validate)
    g.route(validate, SingleExit.DONE, emit)

    # Every path through the graph ends here. Terminal has no collaborators,
    # so it is built here rather than passed in.
    g.route(emit, SingleExit.DONE, Terminal())

    return g
