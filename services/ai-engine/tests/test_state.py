"""
TriageState as a pydantic model. Pins LangGraph's behaviour around it, so an
upgrade that changes it fails here.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from ai_engine.core.state import TriageState, ValidationResult
from ai_engine.graph.build import GraphBuilder
from ai_engine.graph.flow import wire_triage
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode


def test_state_is_frozen(make_state):
    """LangGraph builds a fresh state per node, so an in-place mutation would
    be silently discarded. It must raise instead."""

    with pytest.raises(ValidationError, match="frozen"):
        make_state().iteration = 1


def test_state_rejects_unknown_fields(make_state):
    """Guards direct construction (main.py, tests). An unknown key in a node's
    returned update is rejected by GraphBuilder instead."""

    with pytest.raises(ValidationError, match="extra"):
        make_state(degraded_reasn="typo")


def test_a_wrong_typed_update_fails_the_run(triage_nodes, make_state):
    """LangGraph validates merged state before the next node. A wrong-typed
    update must abort the run (a 500 core-api routes to a human), never
    flow on into TrustSignals.
    """

    class BrokenRetrieve(HybridRetrieveNode):
        def __call__(self, state):
            return {"candidates": "not a list"}

    nodes = triage_nodes()
    nodes["retrieve"] = BrokenRetrieve(db=nodes["emit"]._db, embedder=None)
    graph = wire_triage(**nodes).compile(TriageState)

    with pytest.raises(ValidationError, match="candidates"):
        graph.invoke(make_state())


def test_missing_validation_reads_as_every_check_failed(make_state):
    """emit_signals falls back to this when validate never ran; a default of
    anything but "failed" would hand the trust scorer passing checks nobody
    performed."""

    assert make_state().validation is None
    failed = ValidationResult.all_failed()
    assert not any(
        [
            failed.schema_valid,
            failed.quote_applicable,
            failed.quote_source_in_topk,
            failed.negation_consistent,
            failed.category_consistent,
        ]
    )
    assert failed.quote_match_ratio == 0.0


def test_node_annotation_does_not_override_the_graph_schema():
    """Without `input_schema` pinned in GraphBuilder.compile, LangGraph takes a
    node's input schema from its `state:` annotation — so a node annotated with
    one schema validates its input against that schema in every graph."""

    from typing import TypedDict

    from ai_engine.core.node import BaseNode, Terminal

    class Other(BaseModel):
        required_elsewhere: int

    class _Loose(TypedDict, total=False):
        seen: list[str]

    class AnnotatedNode(BaseNode):
        def __call__(self, state: Other) -> dict:
            return {"seen": ["ran"]}

    node = AnnotatedNode()
    g = GraphBuilder(entry=node)
    g.route(node, AnnotatedNode.Outcome.DONE, Terminal())

    assert g.compile(_Loose).invoke({})["seen"] == ["ran"]
