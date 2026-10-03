"""
One route of a graph: when `source` ends in `outcome`, run `target` next.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_engine.graph.build.node import BaseNode


@dataclass(frozen=True, slots=True)
class Edge:
    """Valid on its own: a source can only be routed on an outcome its class
    produces. Rules that need the other edges live on `Graph`."""

    source: BaseNode
    outcome: StrEnum
    target: BaseNode

    def __post_init__(self) -> None:
        if not self.source.produces(self.outcome):
            raise ValueError(
                f"{type(self.source).__name__}: routes an outcome it cannot produce "
                f"{self.outcome!r}"
            )
