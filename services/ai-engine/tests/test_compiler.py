"""
GraphBuilder's startup validation. Every wiring mistake must raise at build
time — never mid-run, when the first ticket takes an unusual branch. Uses
throwaway nodes and a mini graph so these tests pin the builder, not the
triage topology (test_build.py does that).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

import pytest

from ai_engine.graph.base import BaseNode, Terminal
from ai_engine.graph.build import GraphBuilder


class _State(TypedDict, total=False):
    flag: bool
    seen: list[str]


class GateNode(BaseNode):
    class Outcome(StrEnum):
        OPEN = "Open"
        SHUT = "Shut"

    def __call__(self, state):
        return {}

    def decide(self, state) -> GateNode.Outcome:
        return self.Outcome.OPEN if state.get("flag") else self.Outcome.SHUT


class WorkNode(BaseNode):
    def __call__(self, state):
        return {"seen": [*state.get("seen", []), self.name]}


class StopNode(BaseNode):
    def __call__(self, state):
        return {}


class StrayNode(BaseNode):
    def __call__(self, state):
        return {}


def _wire(gate=None, work=None, stop=None) -> GraphBuilder:
    gate, work, stop = gate or GateNode(), work or WorkNode(), stop or StopNode()
    g = GraphBuilder(entry=gate)
    g.route(gate, GateNode.Outcome.OPEN, work)
    g.route(gate, GateNode.Outcome.SHUT, stop)
    g.route(work, WorkNode.Outcome.DONE, stop)
    g.route(stop, StopNode.Outcome.DONE, Terminal())
    return g


def test_valid_graph_compiles_and_routes():
    app = _wire().compile(_State)

    assert app.invoke({"flag": True})["seen"] == ["work"]
    assert "seen" not in app.invoke({"flag": False})


def test_name_is_derived_from_class_name():
    class InjectionGuardNode(BaseNode):
        def __call__(self, state):
            return {}

    assert InjectionGuardNode.name == "injection_guard"


def test_class_named_exactly_node_is_rejected():
    with pytest.raises(TypeError, match="Node"):

        class Node(BaseNode):
            def __call__(self, state):
                return {}


def test_unrouted_outcome_raises():
    gate, stop = GateNode(), StopNode()
    g = GraphBuilder(entry=gate)
    g.route(gate, GateNode.Outcome.OPEN, stop)
    g.route(stop, StopNode.Outcome.DONE, Terminal())

    with pytest.raises(ValueError, match="GateNode: unrouted"):
        g.compile(_State)


def test_target_with_no_routes_raises():
    """A node reached only as a target, whose own outcomes were never
    routed, would have no outgoing edge — LangGraph would stop there."""

    gate, stop = GateNode(), StopNode()
    g = GraphBuilder(entry=gate)
    g.route(gate, GateNode.Outcome.OPEN, StrayNode())
    g.route(gate, GateNode.Outcome.SHUT, stop)
    g.route(stop, StopNode.Outcome.DONE, Terminal())

    with pytest.raises(ValueError, match="StrayNode: unrouted"):
        g.compile(_State)


def test_misrouted_target_leaves_node_unreachable():
    """Nodes are discovered by walking from the entry, so a route aimed at
    the wrong node silently drops the intended one from the traversal. Its
    own declared routes are what give it away."""

    gate, work, stop = GateNode(), WorkNode(), StopNode()
    g = GraphBuilder(entry=gate)
    g.route(gate, GateNode.Outcome.OPEN, stop)  # meant: work
    g.route(gate, GateNode.Outcome.SHUT, stop)
    g.route(work, WorkNode.Outcome.DONE, stop)
    g.route(stop, StopNode.Outcome.DONE, Terminal())

    with pytest.raises(ValueError, match=r"unreachable: \['WorkNode'\]"):
        g.compile(_State)


def test_class_instead_of_instance_raises():
    g = GraphBuilder(entry=GateNode())

    with pytest.raises(TypeError, match="pass an instance of StopNode"):
        g.route(WorkNode(), WorkNode.Outcome.DONE, StopNode)
    with pytest.raises(TypeError, match="pass an instance of GateNode"):
        GraphBuilder(entry=GateNode)


def test_terminal_cannot_be_routed_onward():
    """Terminal's only exit is the END edge compile() adds; a second route
    out of it would let a run continue past the point it claims to stop."""

    end = Terminal()
    g = GraphBuilder(entry=WorkNode())

    with pytest.raises(ValueError, match="cannot be routed onward"):
        g.route(end, Terminal.Outcome.DONE, StopNode())


def test_graph_without_reachable_terminal_raises():
    """Every outcome routed and no Terminal means every run cycles until
    LangGraph's recursion limit aborts it — a 500, not a degrade-to-human."""

    a, b = WorkNode(), StopNode()
    g = GraphBuilder(entry=a)
    g.route(a, WorkNode.Outcome.DONE, b)
    g.route(b, StopNode.Outcome.DONE, a)

    with pytest.raises(ValueError, match="no Terminal is reachable"):
        g.compile(_State)


def test_terminal_is_a_real_step_before_end():
    app = _wire().compile(_State)
    edges = {(e.source, e.target) for e in app.get_graph().edges}

    assert ("stop", "terminal") in edges
    assert ("terminal", "__end__") in edges
    assert [e for e in edges if e[1] == "__end__"] == [("terminal", "__end__")]


def test_duplicate_route_raises():
    work = WorkNode()
    g = GraphBuilder(entry=work)
    g.route(work, WorkNode.Outcome.DONE, Terminal())

    with pytest.raises(ValueError, match="already routed"):
        g.route(work, WorkNode.Outcome.DONE, StopNode())


def test_two_instances_of_one_node_raise():
    """LangGraph identifies nodes by name, so two instances of one class in
    one graph would collide."""

    gate, stop, first, second = GateNode(), StopNode(), WorkNode(), WorkNode()
    g = GraphBuilder(entry=gate)
    g.route(gate, GateNode.Outcome.OPEN, first)
    g.route(gate, GateNode.Outcome.SHUT, second)
    g.route(first, WorkNode.Outcome.DONE, stop)
    g.route(second, WorkNode.Outcome.DONE, stop)
    g.route(stop, StopNode.Outcome.DONE, Terminal())

    with pytest.raises(ValueError, match="WorkNode was given more than one instance"):
        g.compile(_State)


def test_outcome_from_another_node_raises():
    g = GraphBuilder(entry=WorkNode())

    with pytest.raises(ValueError, match="cannot produce"):
        g.route(g.entry, GateNode.Outcome.OPEN, StopNode())


def test_equal_valued_outcome_from_another_enum_raises():
    """Outcome is a StrEnum, so `Other.DONE == BaseNode.Outcome.DONE` is
    True. Membership must be checked by identity or a foreign outcome that
    decide() can never return would pass as routed."""

    class Other(StrEnum):
        DONE = "Done"

    g = GraphBuilder(entry=WorkNode())

    with pytest.raises(ValueError, match="cannot produce"):
        g.route(g.entry, Other.DONE, Terminal())


def test_custom_outcome_without_decide_raises():
    class ForkNode(BaseNode):
        class Outcome(StrEnum):
            LEFT = "Left"
            RIGHT = "Right"

        def __call__(self, state):
            return {}

    fork, stop = ForkNode(), StopNode()
    g = GraphBuilder(entry=fork)
    g.route(fork, ForkNode.Outcome.LEFT, stop)
    g.route(fork, ForkNode.Outcome.RIGHT, stop)
    g.route(stop, StopNode.Outcome.DONE, Terminal())

    with pytest.raises(ValueError, match="does not override decide"):
        g.compile(_State)


def test_one_node_class_serves_two_graphs_with_different_routes():
    """Routes live on the builder, not on the class or its Outcome members —
    wiring one graph must not rewire another. Both share
    BaseNode.Outcome.DONE, the member every single-exit node inherits."""

    gate, work, stop = GateNode(), WorkNode(), StopNode()
    first = _wire(gate, work, stop).compile(_State)

    solo = WorkNode()
    g = GraphBuilder(entry=solo)
    g.route(solo, WorkNode.Outcome.DONE, Terminal())
    second = g.compile(_State)

    assert first.invoke({"flag": True})["seen"] == ["work"]
    assert second.invoke({})["seen"] == ["work"]
    assert ("work", "stop") in {(e.source, e.target) for e in first.get_graph().edges}
    assert ("work", "terminal") in {(e.source, e.target) for e in second.get_graph().edges}


def test_subclass_fake_routes_in_place_of_the_real_node():
    """The test seam: any instance can be wired where the real one would be.
    It registers under its own class name, so traces show the fake ran."""

    class FakeWorkNode(WorkNode):
        def __call__(self, state):
            return {"seen": ["fake"]}

    app = _wire(work=FakeWorkNode()).compile(_State)

    assert app.invoke({"flag": True})["seen"] == ["fake"]
    assert "fake_work" in app.get_graph().nodes
