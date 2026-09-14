"""
compile_graph's startup validation. Every wiring mistake must raise at
build time — never mid-run, when the first ticket takes an unusual branch.
Uses throwaway nodes and a mini flow so these tests pin the compiler, not
the triage topology (test_build.py does that).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

import pytest

from ai_engine.graph.base import BaseNode, Terminal
from ai_engine.graph.build import compile_graph


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


def _flow():
    return {
        GateNode: {GateNode.Outcome.OPEN: WorkNode, GateNode.Outcome.SHUT: StopNode},
        WorkNode: {WorkNode.Outcome.DONE: StopNode},
        StopNode: {StopNode.Outcome.DONE: Terminal},
    }


def _nodes():
    return [GateNode(), WorkNode(), StopNode()]


def test_valid_flow_compiles_and_routes():
    app = compile_graph(_State, _nodes(), _flow(), GateNode)

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
    flow = _flow()
    del flow[GateNode][GateNode.Outcome.SHUT]

    with pytest.raises(ValueError, match="unrouted"):
        compile_graph(_State, _nodes(), flow, GateNode)


def test_dangling_target_raises():
    flow = _flow()
    flow[WorkNode] = {WorkNode.Outcome.DONE: StrayNode}

    with pytest.raises(ValueError, match="StrayNode: no instance"):
        compile_graph(_State, _nodes(), flow, GateNode)


def test_unreachable_node_raises():
    flow = {**_flow(), StrayNode: {StrayNode.Outcome.DONE: Terminal}}

    with pytest.raises(ValueError, match="unreachable"):
        compile_graph(_State, [*_nodes(), StrayNode()], flow, GateNode)


def test_instance_without_flow_entry_raises():
    with pytest.raises(ValueError, match="has no flow entry"):
        compile_graph(_State, [*_nodes(), StrayNode()], _flow(), GateNode)


def test_flow_entry_without_instance_raises():
    with pytest.raises(ValueError, match="no instance was given"):
        compile_graph(_State, [GateNode(), StopNode()], _flow(), GateNode)


def test_entry_without_instance_raises():
    with pytest.raises(ValueError, match="entry StrayNode"):
        compile_graph(_State, _nodes(), _flow(), StrayNode)


def test_duplicate_instance_raises():
    with pytest.raises(ValueError, match="more than one instance"):
        compile_graph(_State, [*_nodes(), WorkNode()], _flow(), GateNode)


def test_outcome_from_another_node_raises():
    flow = _flow()
    flow[WorkNode] = {WorkNode.Outcome.DONE: StopNode, GateNode.Outcome.OPEN: StopNode}

    with pytest.raises(ValueError, match="cannot produce"):
        compile_graph(_State, _nodes(), flow, GateNode)


def test_custom_outcome_without_decide_raises():
    class ForkNode(BaseNode):
        class Outcome(StrEnum):
            LEFT = "Left"
            RIGHT = "Right"

        def __call__(self, state):
            return {}

    flow = {
        ForkNode: {ForkNode.Outcome.LEFT: StopNode, ForkNode.Outcome.RIGHT: StopNode},
        StopNode: {StopNode.Outcome.DONE: Terminal},
    }

    with pytest.raises(ValueError, match="does not override decide"):
        compile_graph(_State, [ForkNode(), StopNode()], flow, ForkNode)


def test_subclass_instance_is_wired_under_the_flow_class_name():
    class FakeWorkNode(WorkNode):
        def __call__(self, state):
            return {"seen": ["fake"]}

    app = compile_graph(_State, [GateNode(), FakeWorkNode(), StopNode()], _flow(), GateNode)

    assert WorkNode.name in app.get_graph().nodes
    assert "fake_work" not in app.get_graph().nodes
    assert app.invoke({"flag": True})["seen"] == ["fake"]
