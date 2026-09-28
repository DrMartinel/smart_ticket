"""
Wire-contract parity between core-api and ai-engine (ADR-0010).

Each service holds its own copy of the schemas it needs, so the shapes that
cross the wire — `AIRunRequest` (core-api → ai-engine) and `AIRunResponse`
(ai-engine → core-api), plus every type nested in them — are defined twice.
Nothing at import time stops the two copies from drifting, and the drift
does not fail loudly: a field renamed on one side reaches the other as a
422 on every ticket, or worse, as a field silently left at its default
(`quote_applicable=True`, `degraded_reason=None`) that lets a degraded run
look healthy to the router.

This suite is the only thing that catches it, so it compares the full JSON
schema of both copies, not a hand-picked field list. Runs offline: both
copies are plain Pydantic models.
"""

from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel

import contracts as core
from ai_engine import contracts as engine

# Every model and enum that ai-engine's copy defines is on the wire, so it
# must match core-api's copy. Listed explicitly (not discovered) so a type
# added to one copy only shows up here as a missing-name failure.
_WIRE_MODELS = [
    "AIRunRequest",
    "AIRunResponse",
    "TicketMasked",
    "AutoReplyProposal",
    "RouteProposal",
    "RunbookProposal",
    "InsufficientContext",
    "LLMProposalEnvelope",
    "RetrievalSignals",
    "GenerationSignals",
    "PolicySignals",
    "TrustSignals",
]
_WIRE_ENUMS = ["PIILevel", "TicketCategory"]


def _strip_descriptions(node: Any) -> Any:
    """Docstrings become `description` in the schema. They are prose, and
    the two copies are allowed to explain themselves differently; shape,
    names, types, constraints and defaults are not."""
    if isinstance(node, dict):
        return {k: _strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_descriptions(v) for v in node]
    return node


@pytest.mark.parametrize("name", _WIRE_MODELS)
def test_wire_model_schema_matches(name: str) -> None:
    core_model: type[BaseModel] = getattr(core, name)
    engine_model: type[BaseModel] = getattr(engine, name)
    for mode in ("validation", "serialization"):
        assert _strip_descriptions(
            engine_model.model_json_schema(mode=mode)
        ) == _strip_descriptions(core_model.model_json_schema(mode=mode)), (
            f"{name} ({mode}) differs between services/core-api/contracts and "
            f"services/ai-engine/src/ai_engine/contracts — change both in the same PR"
        )


@pytest.mark.parametrize("name", _WIRE_ENUMS)
def test_wire_enum_values_match(name: str) -> None:
    core_enum: type[StrEnum] = getattr(core, name)
    engine_enum: type[StrEnum] = getattr(engine, name)
    assert [(m.name, m.value) for m in engine_enum] == [(m.name, m.value) for m in core_enum]


def test_engine_copy_exports_only_wire_types() -> None:
    """ai-engine's copy is deliberately trimmed: no `Branch`, `ReasonCode`,
    `RoutingDecision` or `TrustScore`, because ai-engine has no authority to
    choose a branch or score itself (ADR-0001, ADR-0003). A name added to
    its `__all__` without a parity check above fails here, which forces the
    question of whether it belongs on the ai-engine side at all."""
    assert sorted(engine.__all__) == sorted(_WIRE_MODELS + _WIRE_ENUMS + ["LLMProposal"])
