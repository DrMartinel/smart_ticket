"""
The triage graph — spec §6.2: the triage route list and `triage_graph`,
compiled once at import. `main.py` only invokes `triage_graph`;
`tests/test_build.py` pins its nodes and edges literally.

The generic machinery lives in `core/build/` and knows nothing about triage:
`Edge` is one route, `Graph` holds the edges and proves them sound, and
`GraphBuilder` declares a `Graph` and compiles it to LangGraph. Importing
those never compiles this graph.

Triage topology, load-bearing properties:

1. No node writes to a business database. Nodes only read (via `ai_engine_ro`,
   ADR-0004) or compute; core-api makes every decision.
2. Refuse-before-LLM: a top rerank score below `retrieval_floor` routes
   straight to `EmitSignalsNode`, never reaching `InferNode`.
3. The graph is acyclic: every node runs at most once per ticket. A proposal
   that fails schema validation goes to a human, not back to the model.
   `Graph.validate()` rejects any cycle.
"""

from __future__ import annotations

from ai_engine.core.node import SingleExit
from ai_engine.core.state import TriageState
from ai_engine.core.build.builder import GraphBuilder
from ai_engine.graph.nodes.emit_signals import emit_signals
from ai_engine.graph.nodes.fewshot import select_fewshots
from ai_engine.graph.nodes.infer import infer
from ai_engine.graph.nodes.injection import InjectionOutcome, injection
from ai_engine.graph.nodes.rerank import RerankOutcome, rerank
from ai_engine.graph.nodes.retrieve import hybrid_retrieve
from ai_engine.graph.nodes.validate import validate

_triage = GraphBuilder(entry=injection)

_triage.route(injection, InjectionOutcome.INJECTION_DETECTED, emit_signals)
_triage.route(injection, InjectionOutcome.INJECTION_CLEAR, hybrid_retrieve)

_triage.route(hybrid_retrieve, SingleExit.DONE, rerank)

_triage.route(rerank, RerankOutcome.EVIDENCE_BELOW_FLOOR, emit_signals)  # refuse-before-LLM
_triage.route(rerank, RerankOutcome.EVIDENCE_ABOVE_FLOOR, select_fewshots)

_triage.route(select_fewshots, SingleExit.DONE, infer)
_triage.route(infer, SingleExit.DONE, validate)
_triage.route(validate, SingleExit.DONE, emit_signals)  # no cycle: schema failure goes to HITL

_triage.route(emit_signals, SingleExit.DONE, _triage.end)  # every path ends here

triage_graph = _triage.compile(TriageState)
