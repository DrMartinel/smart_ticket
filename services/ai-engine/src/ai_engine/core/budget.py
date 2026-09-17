"""
Budget guard — spec §6.2, §10.2.

Every expensive node (retrieve, rerank, infer) inherits `BudgetedNode`, so the
check runs on every pass through the validate → infer retry loop, not just
once at graph entry. It is a cost control and a security control: an
adversarial ticket could otherwise loop through its budget.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from ai_engine.core.node import BaseNode
from ai_engine.core.state import TriageState


class BudgetExceeded(Exception):
    """Raised by `check_budget`, caught by `BudgetedNode`'s wrapper.

    Must never escape a node: that aborts `graph.invoke` and turns a
    degrade-to-human into a 500 with no TrustSignals.
    """

    reason = "budget_exceeded"  # the degraded_reason core-api routes on


def check_budget(state: TriageState) -> None:
    """Raise `BudgetExceeded` if any per-request limit is spent.

    Limits arrive in state from core-api's thresholds.yaml; ai-engine owns
    no budget numbers.
    """

    spent_vs_limit = {
        "graph_iterations": (state.iteration, state.max_graph_iterations),
        "llm_calls": (state.llm_calls, state.max_llm_calls),
        "tokens": (state.tokens_used, state.max_tokens),
        "latency_sec": (time.time() - state.started_at, state.max_latency_sec),
    }
    for limit_name, (spent, limit) in spent_vs_limit.items():
        if spent >= limit:
            raise BudgetExceeded(limit_name)


class BudgetedNode(BaseNode):
    """A node that spends tokens, latency or a network round-trip.

    Its `__call__` is wrapped with the budget check at class definition,
    so no subclass — even one overriding `__call__` again — can skip it.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own_call = cls.__dict__.get("__call__")
        if own_call is None:
            return

        @functools.wraps(own_call)
        def guarded_call(self: Any, state: TriageState) -> dict:
            try:
                check_budget(state)
            except BudgetExceeded as e:
                return {"degraded_reason": e.reason}
            return own_call(self, state)

        cls.__call__ = guarded_call
