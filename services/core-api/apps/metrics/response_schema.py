"""
Response shape of the dashboard (spec §11.1), grouped as the spec groups it.

Rows from `.values()` keep their ORM lookup names (`reviewer__username`,
`review_item__ticket__category`) because those are the keys the web client
already reads.
"""

from __future__ import annotations

from ninja import Schema


class CategoryOverridesOut(Schema):
    review_item__ticket__category: str | None
    n: int


class QualityOut(Schema):
    reopen_rate_after_autoreply: float | None
    override_rate: float | None
    override_rate_by_category: list[CategoryOverridesOut]
    reroute_rate: float | None
    refusal_rate: float | None
    hallucination_catch_rate: float | None


class QueueDepthOut(Schema):
    queue: str
    n: int


class ReviewerStatsOut(Schema):
    reviewer_id: int
    reviewer__username: str
    total: int
    approved: int
    approve_rate: float | None
    median_time_spent_sec: float | None


class HitlHealthOut(Schema):
    queue_depth_by_queue: list[QueueDepthOut]
    time_in_queue_p50_sec: float | None
    time_in_queue_p95_sec: float | None
    approve_rate_per_reviewer: list[ReviewerStatsOut]


class OpsOut(Schema):
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    cost_per_ticket_usd: float | None
    degraded_run_ratio: float | None
    circuit_open_events: int


class BusinessOut(Schema):
    automation_rate: float | None
    sla_compliance: float | None


class DashboardOut(Schema):
    quality: QualityOut
    hitl_health: HitlHealthOut
    ops: OpsOut
    business: BusinessOut
