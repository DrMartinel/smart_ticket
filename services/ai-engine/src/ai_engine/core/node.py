"""
Node contract — see docs/graph-node-architecture.md.

A node owns exactly five things: its name (derived from the class name), its
`__init__` (dependencies only), its `__call__` (the work), its `decide()`
(which business outcome it reached) and its `Outcome` enum. It never knows
what runs after it — that lives in `graph/flow.py`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, ClassVar

from ai_engine.core.state import TriageState


class BaseNode(ABC):
    """One unit of work in the triage graph.

    Read-only after __init__: one instance is shared across FastAPI's
    threadpool, so `__call__` must never write to `self`. All per-call data
    belongs in state.
    """

    name: ClassVar[str]

    class Outcome(StrEnum):
        """Business meanings this node can end in. Subclasses override."""

        DONE = "Done"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        stem = re.sub(r"Node$", "", cls.__name__)  # InjectionNode
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()  # -> "injection"
        if not name:
            raise TypeError(f"{cls.__qualname__}: a node class cannot be named exactly 'Node'")
        cls.name = name

    @abstractmethod
    def __call__(self, state: TriageState) -> dict:
        """Do the work. Return only the state keys that changed."""

    def decide(self, state: TriageState) -> BaseNode.Outcome:
        """Which outcome did this run reach? Runs after __call__'s update is
        merged, so it sees fresh state. Default: single exit."""
        return self.Outcome.DONE


class Terminal(BaseNode):
    """The node every path ends on. Keeps LangGraph's END out of app code:
    `GraphBuilder.compile` gives it the only edge to END, so it is never
    routed onward.

    It changes no state, and must not return END or any other key outside
    TriageState: LangGraph silently drops an unknown update key, so it would
    look like it worked while doing nothing.
    """

    class Outcome(StrEnum):
        DONE = "Done"

    def __call__(self, state: TriageState) -> dict:
        return {}
