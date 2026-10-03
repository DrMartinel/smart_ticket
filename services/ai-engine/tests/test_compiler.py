"""
GraphBuilder's startup validation: every wiring mistake must raise at build
time, not mid-run. Uses throwaway nodes so these pin the builder, not the
triage topology (test_build.py).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

import pytest

from ai_engine.graph.build.node import BaseNode, SingleExit, Terminal, terminal
from ai_engine.graph.build.builder import GraphBuilder


class _State(TypedDict, total=False):
    flag: bool
    seen: list[str]


class GateOutcome(StrEnum):
    OPEN = "Open"
    SHUT = "Shut"


class GateNode(BaseNode):
    Outcome = GateOutcome

    def __call__(self, state):
        return {}

    def decide(self, state: Any) -> GateOutcome:
        return GateOutcome.OPEN if state.get("flag") else GateOutcome.SHUT


class WorkNode(BaseNode):
    def __call__(self, state: Any):
        return {"seen": [*state.get("seen", []), self.name]}


class StopNode(BaseNode):
    def __call__(self, state):
        return {}


class StrayNode(BaseNode):
    def __call__(self, state):
        return {}


# One instance per class, shared by every test: routes live on each builder,
# so wiring one test's graph does not rewire another's.
gate, work, stop, stray = GateNode(), WorkNode(), StopNode(), StrayNode()


def _wire(work: BaseNode = work) -> GraphBuilder:
    g = GraphBuilder(entry=gate)
    g.route(gate, GateOutcome.OPEN, work)
    g.route(gate, GateOutcome.SHUT, stop)
    g.route(work, SingleExit.DONE, stop)
    g.route(stop, SingleExit.DONE, g.end)
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
    g = GraphBuilder(entry=gate)
    g.route(gate, GateOutcome.OPEN, stop)
    g.route(stop, SingleExit.DONE, g.end)

    with pytest.raises(ValueError, match="GateNode: unrouted"):
        g.compile(_State)


def test_target_with_no_routes_raises():
    """A node reached only as a target, whose own outcomes were never
    routed, would have no outgoing edge — LangGraph would stop there."""

    g = GraphBuilder(entry=gate)
    g.route(gate, GateOutcome.OPEN, stray)
    g.route(gate, GateOutcome.SHUT, stop)
    g.route(stop, SingleExit.DONE, g.end)

    with pytest.raises(ValueError, match="StrayNode: unrouted"):
        g.compile(_State)


def test_misrouted_target_leaves_node_unreachable():
    """A route aimed at the wrong node drops the intended one from traversal;
    its own declared routes give it away.
    """

    g = GraphBuilder(entry=gate)
    g.route(gate, GateOutcome.OPEN, stop)  # meant: work
    g.route(gate, GateOutcome.SHUT, stop)
    g.route(work, SingleExit.DONE, stop)
    g.route(stop, SingleExit.DONE, g.end)

    with pytest.raises(ValueError, match=r"unreachable: \['WorkNode'\]"):
        g.compile(_State)


def test_terminal_cannot_be_routed_onward():
    """Terminal's only exit is the END edge compile() adds; a second route
    out of it would let a run continue past the point it claims to stop."""

    g = GraphBuilder(entry=work)

    with pytest.raises(ValueError, match="cannot be routed onward"):
        g.route(g.end, SingleExit.DONE, stop)


def test_graph_without_reachable_terminal_raises():
    """Every outcome routed and no route to the end means every run cycles until
    LangGraph's recursion limit aborts it — a 500, not a degrade-to-human."""

    g = GraphBuilder(entry=work)
    g.route(work, SingleExit.DONE, stop)
    g.route(stop, SingleExit.DONE, work)

    with pytest.raises(ValueError, match="no route reaches the end"):
        g.compile(_State)


def test_cycle_raises_even_when_the_end_is_reachable():
    """Every node runs at most once per run. A loop back — the shape of
    "retry the model on a bad proposal" — must fail at build time, so a
    failure reaches a human instead of the model getting another attempt."""

    g = GraphBuilder(entry=gate)
    g.route(gate, GateOutcome.OPEN, work)
    g.route(gate, GateOutcome.SHUT, stop)
    g.route(work, SingleExit.DONE, gate)  # loops back
    g.route(stop, SingleExit.DONE, g.end)

    with pytest.raises(
        ValueError,
        match=r"cycle: (GateNode -> WorkNode -> GateNode|WorkNode -> GateNode -> WorkNode)$",
    ):
        g.compile(_State)


def test_a_terminal_subclass_is_not_an_end():
    """Only `builder.end` finishes a path: it is recognised by identity, not
    type. A Terminal subclass is an ordinary node, so a graph routed into one
    has no end — rather than silently gaining a second one."""

    class StrayTerminal(Terminal):
        pass

    g = GraphBuilder(entry=work)
    g.route(work, SingleExit.DONE, StrayTerminal())

    with pytest.raises(ValueError, match="no route reaches the end"):
        g.compile(_State)


def test_terminal_is_a_real_step_before_end():
    app = _wire().compile(_State)
    edges = {(e.source, e.target) for e in app.get_graph().edges}

    assert ("stop", "terminal") in edges
    assert ("terminal", "__end__") in edges
    assert [e for e in edges if e[1] == "__end__"] == [("terminal", "__end__")]


def test_duplicate_route_raises():
    g = GraphBuilder(entry=work)
    g.route(work, SingleExit.DONE, g.end)

    with pytest.raises(ValueError, match="already routed"):
        g.route(work, SingleExit.DONE, stop)


def test_second_instance_of_a_node_class_raises():
    """Production wires the instance each node module creates. A second one,
    built by hand and routed in its place, would be a different object that
    the rest of the code never sees."""

    with pytest.raises(TypeError, match="WorkNode already has an instance"):
        WorkNode()


def test_every_builder_ends_on_the_one_terminal():
    """Terminal follows one-instance-per-class like every node. Builders share
    it; routes live on each builder, so sharing it rewires nothing."""

    assert GraphBuilder(entry=work).end is GraphBuilder(entry=gate).end is terminal
    with pytest.raises(TypeError, match="Terminal already has an instance"):
        Terminal()


def test_two_classes_with_one_name_raise():
    """The node name comes from the class name alone, so two classes both
    called WorkNode collide as one LangGraph node."""

    class WorkNode(BaseNode):  # same name as the module-level WorkNode
        def __call__(self, state):
            return {}

    impostor = WorkNode()
    g = GraphBuilder(entry=gate)
    g.route(gate, GateOutcome.OPEN, work)
    g.route(gate, GateOutcome.SHUT, impostor)
    g.route(work, SingleExit.DONE, stop)
    g.route(impostor, SingleExit.DONE, stop)
    g.route(stop, SingleExit.DONE, g.end)

    with pytest.raises(ValueError, match="'work' is claimed by two node classes"):
        g.compile(_State)


def test_outcome_from_another_node_raises():
    g = GraphBuilder(entry=work)

    with pytest.raises(ValueError, match="cannot produce"):
        g.route(work, GateOutcome.OPEN, stop)


def test_equal_valued_outcome_from_another_enum_raises():
    """Outcome is a StrEnum, so `Other.DONE == SingleExit.DONE` is
    True. Membership must be checked by identity or a foreign outcome that
    decide() can never return would pass as routed."""

    class Other(StrEnum):
        DONE = "Done"

    g = GraphBuilder(entry=work)

    with pytest.raises(ValueError, match="cannot produce"):
        g.route(work, Other.DONE, g.end)


def test_custom_outcome_without_decide_raises():
    """The inherited decide() returns SingleExit.DONE, which ForkOutcome does
    not contain, so every run would end on an unrouted outcome. BaseNode
    rejects the class when it is defined, before it can be wired anywhere."""

    class ForkOutcome(StrEnum):
        LEFT = "Left"
        RIGHT = "Right"

    with pytest.raises(TypeError, match="does not override decide"):

        class ForkNode(BaseNode):
            Outcome = ForkOutcome

            def __call__(self, state):
                return {}


def test_one_node_class_serves_two_graphs_with_different_routes():
    """Routes live on the builder, not on the class or its Outcome members —
    wiring one graph must not rewire another. Both share
    SingleExit.DONE, the member every single-exit node inherits."""

    first = _wire().compile(_State)

    g = GraphBuilder(entry=work)
    g.route(work, SingleExit.DONE, g.end)
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


def test_update_key_missing_from_the_schema_raises():
    """LangGraph silently drops an update key that is not a state field, so a
    misspelled key would look like it worked. It must raise instead."""

    class TypoNode(BaseNode):
        def __call__(self, state):
            return {"sean": ["typo"]}

    node = TypoNode()
    g = GraphBuilder(entry=node)
    g.route(node, SingleExit.DONE, g.end)

    with pytest.raises(ValueError, match=r"TypoNode returned keys .* \['sean'\]"):
        g.compile(_State).invoke({})
