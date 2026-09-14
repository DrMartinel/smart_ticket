"""
Budget guard — spec §6.2 ("guard_budget — gọi lại trước mỗi node tốn kém")
and §10.2.

Every expensive node (retrieve, rerank, infer) inherits `BudgetedNode`, which
checks the per-request budget before the node runs. Building the check into
the node, rather than adding a separate guard node, means it runs on every
pass through the validate → infer retry loop, not just once at graph entry.

This is a cost control and a security control: an adversarial ticket
engineered to trigger the retry loop could otherwise burn through budget in
minutes.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from ai_engine.graph.base import BaseNode
from ai_engine.graph.state import TriageState


class BudgetExceeded(Exception):
    """Raised by `check_budget`; caught by the wrapper `BudgetedNode` puts
    around each node's `__call__`.

    Never let it escape a node: an uncaught one aborts `graph.invoke`, turning
    a degrade-to-human into a 500 with no TrustSignals.
    """

    reason = "budget_exceeded"  # the degraded_reason core-api routes on


def check_budget(state: TriageState) -> None:
    """Raise `BudgetExceeded` if any per-request limit is spent.

    The limits arrive in state from AIRunRequest, which core-api fills from
    thresholds.yaml — ai-engine itself owns no budget numbers.
    """

    spent_vs_limit = {
        "graph_iterations": (state["iteration"], state["max_graph_iterations"]),
        "llm_calls": (state["llm_calls"], state["max_llm_calls"]),
        "tokens": (state["tokens_used"], state["max_tokens"]),
        "latency_sec": (time.time() - state["started_at"], state["max_latency_sec"]),
    }
    for limit_name, (spent, limit) in spent_vs_limit.items():
        if spent >= limit:
            raise BudgetExceeded(limit_name)


class BudgetedNode(BaseNode):
    """A node that spends tokens, latency or a network round-trip.

    Subclasses write an ordinary `__call__(self, state) -> dict`. When the
    class is defined, that `__call__` is wrapped with the budget check, so the
    check cannot be forgotten — not even by a test fake that subclasses a real
    node and overrides `__call__` again.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own_call = cls.__dict__.get("__call__")
        if own_call is None:
            return

        # functools.wraps keeps the original name and annotations — LangGraph
        # reads __call__'s type hints when the node is registered.
        @functools.wraps(own_call)
        def guarded_call(self: Any, state: TriageState) -> dict:
            # Only the check is inside the try: catching around the node's own
            # work would let a BudgetExceeded raised mid-work discard updates
            # already paid for (llm_calls, tokens_used).
            try:
                check_budget(state)
            except BudgetExceeded as e:
                # Only degraded_reason — none of the node's own keys. Every
                # reader uses .get() with an empty default, so an absent key
                # already means "nothing retrieved / reranked / proposed". And
                # infer, the only node in a loop, is re-entered only when
                # validate found proposal to be None, so a skipped retry leaves
                # no stale proposal behind.
                return {"degraded_reason": e.reason}
            return own_call(self, state)

        cls.__call__ = guarded_call
