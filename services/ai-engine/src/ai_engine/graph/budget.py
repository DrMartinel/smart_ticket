"""
Budget guard — spec §6.2 ("guard_budget — gọi lại trước mỗi node tốn
kém") and §10.2. Rather than a separate graph node with its own routing
(which the spec's own pseudocode leaves informal), this is called at the
START of every expensive node (retrieve, rerank, infer) — cheap, and
guarantees the check actually happens on every pass through the
validate → infer retry loop, not just once at graph entry.

This is both a cost control and a security control (spec §10.2): an
adversarial ticket engineered to trigger the retry loop repeatedly could
otherwise burn through budget in minutes.
"""

from __future__ import annotations

import time

from ai_engine.graph.state import TriageState


def check_budget(state: TriageState) -> str | None:
    """Returns a degraded_reason string if any budget limit is exceeded,
    else None. Checked against the per-request limits carried in state
    (sourced from AIRunRequest, which core-api populates from
    thresholds.yaml — ai-engine itself owns no budget numbers)."""

    if state["iteration"] >= state["max_graph_iterations"]:
        return "budget_exceeded"
    if state["llm_calls"] >= state["max_llm_calls"]:
        return "budget_exceeded"
    if state["tokens_used"] >= state["max_tokens"]:
        return "budget_exceeded"
    if time.time() - state["started_at"] >= state["max_latency_sec"]:
        return "budget_exceeded"
    return None
