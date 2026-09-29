"""
`GraphBuilder`: declares a `Graph` edge by edge, then translates the validated
graph to LangGraph. The only place a node becomes a LangGraph string (node
names, edge targets, START/END).
"""

from __future__ import annotations

from collections.abc import Hashable
from enum import StrEnum
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.typing import StateLike  # pyright: ignore[reportPrivateImportUsage]

from ai_engine.core.node import BaseNode, StateUpdate, terminal
from ai_engine.core.build.edge import Edge
from ai_engine.core.build.graph import Graph


class GraphBuilder:
    """Declares a `Graph` and compiles it to LangGraph.

    - Edges live on the builder's `Graph`, not on node classes:
      `SingleExit.DONE` is shared by every single-exit node, and one class may
      serve several graphs.
    - `builder.end` is the one `Terminal` instance, shared by every builder.
      Routing to it is how a path finishes; it holds the only edge to END.
    - Bad wiring raises in `route()` or `compile()`, at startup — never mid-run.
      That includes any cycle: every graph it builds is acyclic.
    - Every node runs behind an adapter that rejects update keys the state
      schema lacks. LangGraph would drop them silently, so a typo'd key would
      look like it worked.
    """

    def __init__(self, *, entry: BaseNode) -> None:
        self.end = terminal
        self._graph = Graph(entry=entry, end=self.end)

    def route(self, source: BaseNode, outcome: StrEnum, target: BaseNode) -> None:
        """When `source` ends in `outcome`, run `target` next."""
        self._graph.add(Edge(source, outcome, target))

    def compile[S: StateLike](self, state_schema: type[S]) -> CompiledStateGraph[S, None, S, S]:
        """Validate the graph reachable from the entry and compile it.
        Raises ValueError on any wiring mistake, before a ticket ever runs."""
        nodes = self._graph.validate()

        state_graph: StateGraph[S, None, S, S] = StateGraph(state_schema)
        state_keys: set[str] = set(state_graph.channels)

        for node in nodes:
            state_graph.add_node(
                node.name, _reject_unknown_keys(node, state_keys), input_schema=state_schema
            )

        state_graph.add_edge(START, self._graph.entry.name)
        for node in nodes:
            if node is self.end:
                state_graph.add_edge(node.name, END)
                continue
            targets: dict[Hashable, str] = {
                edge.outcome: edge.target.name for edge in self._graph.edges_from(node)
            }
            if len(targets) == 1:
                state_graph.add_edge(node.name, next(iter(targets.values())))
            else:
                state_graph.add_conditional_edges(node.name, node.decide, targets)

        return state_graph.compile()


# A function, not inlined into compile()'s loop: each wrapper must capture its
# own node. A closure defined in the loop body would see only the last one.
def _reject_unknown_keys(node: BaseNode, state_keys: set[str]):
    """Wrap `node` so an update it returns may only use known state keys.
    A non-dict update still raises — here (`set(None)`, a string's
    characters as keys) or in LangGraph (an empty list) — so no check here."""

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
