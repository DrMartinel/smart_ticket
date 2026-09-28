"""
Node contract — see docs/graph-node-architecture.md.

A node owns exactly four things: its name (derived from the class name), its
`__call__` (the work), its `decide()` (which business outcome it reached) and
its `Outcome` enum. It uses the provider singletons (`db`, `embedder`,
`reranker`, `models.chat`) directly; tests swap them with the `use_*`
fixtures. It never knows
what runs after it — that lives in `graph/build.py`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, ClassVar, Self

from ai_engine.core.state import TriageState

type StateUpdate = dict[str, Any]


class SingleExit(StrEnum):
    """The outcome of every node with one exit."""

    DONE = "Done"


class BaseNode(ABC):
    """One unit of work in the triage graph.

    Read-only after __init__: one instance is shared across FastAPI's
    threadpool, so `__call__` must never write to `self`. All per-call data
    belongs in state.

    One instance per class, created at the bottom of the node's module.
    Everything else, tests included, imports that instance: a second
    construction raises TypeError.
    """

    name: ClassVar[str]

    Outcome: ClassVar[type[StrEnum]] = SingleExit

    _instantiated: ClassVar[bool] = False

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls._instantiated:
            raise TypeError(
                f"{cls.__qualname__} already has an instance; import it instead of "
                f"constructing another"
            )
        cls._instantiated = True
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        stem = re.sub(r"Node$", "", cls.__name__)  # InjectionNode
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()  # -> "injection"
        if not name:
            raise TypeError(f"{cls.__qualname__}: a node class cannot be named exactly 'Node'")
        cls.name = name
        cls._instantiated = False
        if cls.Outcome is not SingleExit and cls.decide is BaseNode.decide:
            raise TypeError(
                f"{cls.__qualname__} defines its own Outcome but does not override decide()"
            )

    @classmethod
    def produces(cls, outcome: StrEnum) -> bool:
        """Is `outcome` a member of this class's Outcome?"""
        return any(outcome is member for member in cls.Outcome)

    @abstractmethod
    def __call__(self, state: TriageState) -> StateUpdate:
        """Do the work. Return only the state keys that changed."""

    def decide(self, state: TriageState) -> StrEnum:
        """Which outcome did this run reach? Runs after __call__'s update is
        merged, so it sees fresh state. Default: single exit."""
        return SingleExit.DONE


class Terminal(BaseNode):
    """The node every path ends on. Its one instance, `terminal`, is shared by
    every `GraphBuilder` as `builder.end`: the builder recognises it by
    identity and gives it the only edge to END, keeping END out of app code.
    Routes live on each builder, so sharing it cannot leak one graph's wiring
    into another.

    It returns no update: LangGraph silently drops keys outside
    TriageState, so returning END would look like it worked while doing
    nothing.
    """

    def __call__(self, state: TriageState) -> StateUpdate:
        return {}


terminal = Terminal()
