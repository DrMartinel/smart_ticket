"""
Graph compiler — the only place a node class becomes a LangGraph string
(add_node names, edge targets, START/END).

`compile_graph` validates a flow table before registering anything, so
wiring mistakes raise at startup, never mid-run when the first ticket takes
an unusual branch. It is generic: the triage topology lives in `flow.py`,
and `main.py` constructs the nodes and compiles them.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ai_engine.graph.base import BaseNode, Flow, Terminal


def _match_instances(nodes: list[BaseNode], flow: Flow) -> dict[type[BaseNode], BaseNode]:
    """Key each instance by the FLOW class it is an instance of.

    `isinstance` rather than `type(n)`, so a test can pass a subclass of a
    real node (`class FakeInfer(InferNode)`) and have it wired in that
    node's place, under that node's name.
    """

    instances: dict[type[BaseNode], BaseNode] = {}
    for node in nodes:
        matches = [cls for cls in flow if isinstance(node, cls)]
        if not matches:
            raise ValueError(f"{type(node).__name__} has no flow entry")
        if len(matches) > 1:
            raise ValueError(
                f"{type(node).__name__} matches several flow entries: {[c.__name__ for c in matches]}"
            )
        cls = matches[0]
        if cls in instances:
            raise ValueError(f"{cls.__name__} was given more than one instance")
        instances[cls] = node
    return instances


def _validate(instances: dict[type[BaseNode], BaseNode], flow: Flow, entry: type[BaseNode]) -> None:
    if entry not in instances:
        raise ValueError(f"entry {entry.__name__} has no instance")

    # Its own pass first, so a missing instance is reported as that — not as
    # a dangling edge from whichever row happens to point at it.
    if absent := [cls.__name__ for cls in flow if cls not in instances]:
        raise ValueError(f"flow lists {absent} but no instance was given")

    for cls, routes in flow.items():
        if "DONE" not in cls.Outcome.__members__ and cls.decide is BaseNode.decide:
            raise ValueError(f"{cls.__name__} defines its own Outcome but does not override decide()")
        foreign = [o for o in routes if o not in set(cls.Outcome)]
        if foreign:
            raise ValueError(f"{cls.__name__}: routes outcomes it cannot produce {foreign}")
        missing = set(cls.Outcome) - set(routes)
        if missing:
            raise ValueError(f"{cls.__name__}: unrouted {sorted(m.value for m in missing)}")
        for outcome, target in routes.items():
            if target is not Terminal and target not in instances:
                raise ValueError(f"{cls.__name__}.{outcome.value} -> {target.__name__}: no instance")

    seen: set[type[BaseNode]] = set()
    stack: list[type[BaseNode]] = [entry]
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack += [t for t in flow[cls].values() if t is not Terminal]
    if orphans := set(instances) - seen:
        raise ValueError(f"unreachable: {sorted(c.__name__ for c in orphans)}")


def compile_graph(
    state_schema: type,
    nodes: list[BaseNode],
    flow: Flow,
    entry: type[BaseNode],
    checkpointer=None,
):
    instances = _match_instances(nodes, flow)
    _validate(instances, flow, entry)

    graph = StateGraph(state_schema)
    for cls, node in instances.items():
        graph.add_node(cls.name, node)

    for cls, routes in flow.items():
        targets = {o: (END if t is Terminal else t.name) for o, t in routes.items()}
        if len(targets) == 1:  # single exit -> plain edge
            graph.add_edge(cls.name, next(iter(targets.values())))
        else:
            graph.add_conditional_edges(cls.name, instances[cls].decide, targets)

    graph.add_edge(START, entry.name)
    return graph.compile(checkpointer=checkpointer)
