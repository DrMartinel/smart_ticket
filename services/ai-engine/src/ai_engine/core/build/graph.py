"""
The wiring of one graph as a plain directed graph of `Edge`s between node
instances. It answers which nodes a run can reach and whether the wiring is
complete and consistent — and knows nothing about LangGraph. `GraphBuilder`
(`builder.py`) translates a validated `Graph`.
"""

from __future__ import annotations

from enum import StrEnum
from graphlib import CycleError, TopologicalSorter

from ai_engine.core.node import BaseNode
from ai_engine.core.build.edge import Edge


class Graph:
    """Edges from one entry to one end. Every mistake raises ValueError: in
    `add()` as it is declared, or in `validate()` for what only the whole
    graph shows."""

    def __init__(self, *, entry: BaseNode, end: BaseNode) -> None:
        self.entry = entry
        self.end = end
        self._edges: dict[BaseNode, dict[StrEnum, Edge]] = {}

    def add(self, edge: Edge) -> None:
        name = type(edge.source).__name__

        if edge.source is self.end:
            raise ValueError(f"{name} ends the graph and cannot be routed onward")

        exits = self._edges.setdefault(edge.source, {})
        if edge.outcome in exits:
            raise ValueError(f"{name}.{edge.outcome.value} is already routed")
        exits[edge.outcome] = edge

    def edges_from(self, node: BaseNode) -> tuple[Edge, ...]:
        """`node`'s outgoing edges. Empty for the end, and for a node nobody
        routed out of."""
        return tuple(self._edges.get(node, {}).values())

    def validate(self) -> list[BaseNode]:
        """The nodes reachable from the entry, in first-visit order, once the
        wiring among them is proven sound. Order matters only for which error
        you see first."""
        nodes = self._reachable()
        self._check_unique_names(nodes)
        self._check_end_is_reached(nodes)
        self._check_every_outcome_routed(nodes)
        self._check_no_orphans(nodes)
        self._check_acyclic(nodes)
        return nodes

    def _reachable(self) -> list[BaseNode]:
        """Depth-first from the entry, in first-visit order."""
        seen: dict[BaseNode, None] = {}  # insertion-ordered set
        stack = [self.entry]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen[node] = None
                stack += (edge.target for edge in self.edges_from(node))
        return list(seen)

    def _check_unique_names(self, nodes: list[BaseNode]) -> None:
        # The node name comes from the class name alone. BaseNode allows one
        # instance per class, so a clash here is two classes with one name.
        by_name: dict[str, BaseNode] = {}
        for node in nodes:
            if (first := by_name.setdefault(node.name, node)) is not node:
                raise ValueError(
                    f"{node.name!r} is claimed by two node classes: "
                    f"{type(first).__module__}.{type(first).__qualname__} and "
                    f"{type(node).__module__}.{type(node).__qualname__}"
                )

    def _check_end_is_reached(self, nodes: list[BaseNode]) -> None:
        # Every other node has all its outcomes routed, so without the end
        # every run would cycle until LangGraph's recursion limit.
        if self.end not in nodes:
            raise ValueError("no route reaches the end from the entry")

    def _check_every_outcome_routed(self, nodes: list[BaseNode]) -> None:
        for node in nodes:
            if node is self.end:
                continue  # its only exit is END, added by the builder
            cls = type(node)
            routed = {edge.outcome for edge in self.edges_from(node)}
            if missing := set(cls.Outcome) - routed:
                raise ValueError(f"{cls.__name__}: unrouted {sorted(m.value for m in missing)}")

    def _check_no_orphans(self, nodes: list[BaseNode]) -> None:
        # Traversal can't produce an orphan, but a node whose own edges were
        # declared and that nothing points at can — which is exactly what an
        # edge aimed at the wrong target leaves behind.
        if orphans := [node for node in self._edges if node not in nodes]:
            raise ValueError(f"unreachable: {sorted(type(n).__name__ for n in orphans)}")

    def _check_acyclic(self, nodes: list[BaseNode]) -> None:
        # Every node runs at most once per run: a loop back (say, validate ->
        # infer to retry a bad proposal) would give the model another attempt
        # instead of handing the ticket to a human.
        # TopologicalSorter reads the map as node -> predecessors; handing it
        # successors only reverses the reported cycle, hence [::-1].
        successors = {node: {edge.target for edge in self.edges_from(node)} for node in nodes}
        try:
            TopologicalSorter(successors).prepare()
        except CycleError as e:
            cycle: list[BaseNode] = e.args[1][::-1]
            raise ValueError(f"cycle: {' -> '.join(type(n).__name__ for n in cycle)}") from None
