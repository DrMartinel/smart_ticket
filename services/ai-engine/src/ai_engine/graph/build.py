"""
The triage graph — spec §6.2. Everything that turns nodes into a runnable
LangGraph lives here, top to bottom:

1. `GraphBuilder` — generic: routes a node's outcome to the next node
   instance, validates the wiring, and is the only place a node becomes a
   LangGraph string (node names, edge targets, START/END).
2. The triage topology, as a list of routes on the production node instances.
3. `triage_graph` — the production graph, compiled once at import.

`main.py` only invokes `triage_graph`. `tests/test_build.py` pins its nodes
and edges literally.

Builder guarantees:

- Routes live here, not on node classes: `SingleExit.DONE` is shared by every
  single-exit node, and one class may serve several graphs.
- Each builder owns one `Terminal`, `builder.end`. Routing to it is how a
  path finishes; it holds the only edge to END.
- Bad wiring raises in `route()` or `compile()`, at startup — never mid-run.
- Every node runs behind an adapter that rejects update keys the state schema
  lacks. LangGraph would drop them silently, so a typo'd key would look like
  it worked.

Triage topology, load-bearing properties:

1. No node writes to a business database. Nodes only read (via `ai_engine_ro`,
   ADR-0004) or compute; core-api makes every decision.
2. Refuse-before-LLM: a top rerank score below `retrieval_floor` routes
   straight to `EmitSignalsNode`, never reaching `InferNode`.
3. The graph is acyclic: every node runs at most once per ticket. A proposal
   that fails schema validation goes to a human, not back to the model.
"""

from __future__ import annotations

from collections.abc import Hashable
from enum import Enum
from typing import Any

from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs]
from langgraph.typing import StateLike  # pyright: ignore[reportMissingTypeStubs, reportPrivateImportUsage]

from ai_engine.core.node import BaseNode, SingleExit, StateUpdate, Terminal
from ai_engine.core.state import TriageState
from ai_engine.graph.nodes.emit_signals import emit_signals
from ai_engine.graph.nodes.fewshot import select_fewshots
from ai_engine.graph.nodes.infer import infer
from ai_engine.graph.nodes.injection import InjectionOutcome, injection
from ai_engine.graph.nodes.rerank import RerankOutcome, rerank
from ai_engine.graph.nodes.retrieve import hybrid_retrieve
from ai_engine.graph.nodes.validate import validate


class GraphBuilder:
    def __init__(self, *, entry: BaseNode) -> None:
        self._entry = entry
        self._routes: dict[BaseNode, dict[Enum, BaseNode]] = {}
        self.end = Terminal()

    def route(self, source: BaseNode, outcome: Enum, target: BaseNode) -> None:
        """When `source` ends in `outcome`, run `target` next."""
        name = type(source).__name__

        if source is self.end:
            raise ValueError(f"{name} ends the graph and cannot be routed onward")
        # Identity, not `in`: Outcome is a StrEnum, so a member of another
        # node's enum with the same value ("Done") compares equal.
        if not any(outcome is member for member in type(source).Outcome):
            raise ValueError(f"{name}: routes an outcome it cannot produce {outcome!r}")

        routes = self._routes.setdefault(source, {})
        if outcome in routes:
            raise ValueError(f"{name}.{outcome.value} is already routed")
        routes[outcome] = target

    def compile[S: StateLike](self, state_schema: type[S]) -> CompiledStateGraph[S, None, S, S]:
        # Reachable nodes: depth-first from the entry, in first-visit order.
        seen: dict[BaseNode, None] = {}  # insertion-ordered set
        stack = [self._entry]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen[node] = None
                stack += self._routes.get(node, {}).values()
        nodes = list(seen)

        # --- Validation. Order matters only for which error you see first.

        # The node name comes from its class, so two instances of one class
        # would collide as one LangGraph node.
        by_name: dict[str, BaseNode] = {}
        for node in nodes:
            if by_name.setdefault(node.name, node) is not node:
                raise ValueError(f"{type(node).__name__} was given more than one instance")

        # Every other node has all its outcomes routed, so without the end
        # every run would cycle until LangGraph's recursion limit.
        if self.end not in nodes:
            raise ValueError("no route reaches the end from the entry")

        for node in nodes:
            if node is self.end:
                continue  # its only exit is END, added below
            cls = type(node)
            if cls.Outcome is not SingleExit and cls.decide is BaseNode.decide:
                raise ValueError(
                    f"{cls.__name__} defines its own Outcome but does not override decide()"
                )
            if missing := set(cls.Outcome) - set(self._routes.get(node, {})):
                raise ValueError(f"{cls.__name__}: unrouted {sorted(m.value for m in missing)}")

        # Traversal can't produce an orphan, but a node whose own routes were
        # declared and that nothing points at can — which is exactly what a
        # route aimed at the wrong target leaves behind.
        if orphans := [node for node in self._routes if node not in nodes]:
            raise ValueError(f"unreachable: {sorted(type(n).__name__ for n in orphans)}")

        # --- Translation to LangGraph.

        graph: StateGraph[S, None, S, S] = StateGraph(state_schema)
        state_keys: set[str] = set(graph.channels)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

        for node in nodes:
            # input_schema pinned to the graph's schema: left unset, LangGraph
            # infers it from the `state:` annotation on __call__, so a node
            # annotated with one schema would validate its input against that
            # schema in any graph it is wired into.
            graph.add_node(  # pyright: ignore[reportUnknownMemberType]
                node.name, _reject_unknown_keys(node, state_keys), input_schema=state_schema
            )

        graph.add_edge(START, self._entry.name)
        for node in nodes:
            if node is self.end:
                graph.add_edge(node.name, END)
                continue
            targets: dict[Hashable, str] = {
                outcome: target.name for outcome, target in self._routes[node].items()
            }
            if len(targets) == 1:
                graph.add_edge(node.name, next(iter(targets.values())))
            else:
                graph.add_conditional_edges(node.name, node.decide, targets)

        # No checkpointer: the graph is stateless per request; idempotency
        # lives at the Celery layer in core-api.
        return graph.compile()  # pyright: ignore[reportUnknownMemberType]


# A function, not inlined into compile()'s loop: each wrapper must capture its
# own node. A closure defined in the loop body would see only the last one.
def _reject_unknown_keys(node: BaseNode, state_keys: set[str]):
    """Wrap `node` so an update it returns may only use known state keys.
    (A non-dict update needs no check here: LangGraph rejects it itself.)"""

    def run(state: Any) -> StateUpdate:
        update = node(state)
        if unknown := set(update) - state_keys:
            raise ValueError(
                f"{type(node).__name__} returned keys the state schema does not have "
                f"{sorted(unknown)}"
            )
        return update

    run.node = node  # type: ignore[attr-defined]  # for introspection in tests
    return run


# --- The triage graph -------------------------------------------------------

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
