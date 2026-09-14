"""Structural contract for a graph node."""

from __future__ import annotations

from typing import Protocol

from ai_engine.graph.state import TriageState


class GraphNode(Protocol):
    """Anything passed to `StateGraph.add_node`.

    Typing only — nodes do not inherit from this. A plain function satisfies
    it just as well as a callable instance, which is what keeps the
    function-to-class migration incremental: a half-converted `GraphDeps`
    still typechecks and still wires.
    """

    def __call__(self, state: TriageState) -> dict: ...
