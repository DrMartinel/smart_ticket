"""
Graph builder — the only place a node becomes a LangGraph string
(add_node names, edge targets, START/END).

Routes attach an outcome to the next node *instance*, and live on the
builder rather than on node classes or `Outcome` members:
`BaseNode.Outcome.DONE` is one enum member shared by every single-exit
node, and the same node class may serve more than one graph. Nodes are
never written to, so the "read-only after __init__" rule holds.

Every route targets a node, including the end: a `Terminal` instance is a
real node, and compile() gives it the graph's only edge to END.

`route()` rejects a bad route as it is declared and `compile()` rejects a
bad graph before registering anything, so wiring mistakes raise at
startup, never mid-run when the first ticket takes an unusual branch. It
is generic: the triage topology lives in `flow.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType

from langgraph.graph import END, START, StateGraph

from ai_engine.graph.base import BaseNode, Terminal


def _require_instance(value: object, role: str) -> BaseNode:
    if isinstance(value, type) and issubclass(value, BaseNode):
        raise TypeError(f"{role}: pass an instance of {value.__name__}, not the class")
    if not isinstance(value, BaseNode):
        raise TypeError(f"{role}: expected a BaseNode instance, got {value!r}")
    return value


class GraphBuilder:
    def __init__(self, *, entry: BaseNode) -> None:
        self._entry = _require_instance(entry, "entry")
        self._routes: dict[BaseNode, dict[Enum, BaseNode]] = {}

    @property
    def entry(self) -> BaseNode:
        return self._entry

    @property
    def routes(self) -> Mapping[BaseNode, Mapping[Enum, BaseNode]]:
        """Read-only view of every declared route, for tests and inspection."""
        return MappingProxyType({n: MappingProxyType(r) for n, r in self._routes.items()})

    def route(self, source: BaseNode, outcome: Enum, target: BaseNode) -> None:
        _require_instance(source, "source")
        _require_instance(target, "target")

        cls = type(source)
        if isinstance(source, Terminal):
            raise ValueError(f"{cls.__name__} ends the graph and cannot be routed onward")
        # Identity, not `in`: Outcome is a StrEnum, so a member of another
        # node's enum with the same value ("Done") compares equal.
        if not any(outcome is member for member in cls.Outcome):
            raise ValueError(f"{cls.__name__}: routes an outcome it cannot produce {outcome!r}")

        routes = self._routes.setdefault(source, {})
        if outcome in routes:
            raise ValueError(f"{cls.__name__}.{outcome.value} is already routed")
        routes[outcome] = target

    def _reachable(self) -> list[BaseNode]:
        seen: dict[BaseNode, None] = {}  # insertion-ordered set
        stack = [self._entry]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen[node] = None
            stack += self._routes.get(node, {}).values()
        return list(seen)

    def _validate(self, nodes: list[BaseNode]) -> None:
        by_name: dict[str, BaseNode] = {}
        for node in nodes:
            if by_name.setdefault(node.name, node) is not node:
                raise ValueError(f"{type(node).__name__} was given more than one instance")

        # Every other node has all its outcomes routed, so without a Terminal
        # every run would cycle until LangGraph's recursion limit.
        if not any(isinstance(n, Terminal) for n in nodes):
            raise ValueError("no Terminal is reachable from the entry")

        for node in nodes:
            cls = type(node)
            if isinstance(node, Terminal):
                continue  # its only exit is END, added by compile()
            if "DONE" not in cls.Outcome.__members__ and cls.decide is BaseNode.decide:
                raise ValueError(
                    f"{cls.__name__} defines its own Outcome but does not override decide()"
                )
            missing = set(cls.Outcome) - set(self._routes.get(node, {}))
            if missing:
                raise ValueError(f"{cls.__name__}: unrouted {sorted(m.value for m in missing)}")

        # Traversal can't produce an orphan, but a node whose own routes were
        # declared and that nothing points at can — which is exactly what a
        # route aimed at the wrong target leaves behind.
        if orphans := [n for n in self._routes if n not in nodes]:
            raise ValueError(f"unreachable: {sorted(type(n).__name__ for n in orphans)}")

    def compile(self, state_schema: type, checkpointer=None):
        nodes = self._reachable()
        self._validate(nodes)

        graph = StateGraph(state_schema)
        for node in nodes:
            graph.add_node(node.name, node)

        for node in nodes:
            if isinstance(node, Terminal):
                graph.add_edge(node.name, END)
                continue
            targets = {o: t.name for o, t in self._routes[node].items()}
            if len(targets) == 1:  # single exit -> plain edge
                graph.add_edge(node.name, next(iter(targets.values())))
            else:
                graph.add_conditional_edges(node.name, node.decide, targets)

        graph.add_edge(START, self._entry.name)
        return graph.compile(checkpointer=checkpointer)
