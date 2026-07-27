"""
Dashboard aggregations — spec §11.1, grouped exactly as the spec groups
them (quality / HITL health / ops / business) because that grouping is the
point: quality metrics matter more than everything else, and the two
approval-fatigue metrics exist specifically to check whether HITL is doing
real work or just rubber-stamping (spec: "một HITL bị bấm approve theo
phản xạ còn tệ hơn không có HITL").
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, F, Q
from django.utils import timezone

from apps.review.models import ReviewDecision, ReviewItem
from apps.tickets.models import AiRun, RoutingDecision, Ticket


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def quality_metrics(window_days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=window_days)

    autoreplied = Ticket.objects.filter(
        routing_decisions__branch="auto_reply", created_at__gte=since
    ).distinct()
    reopen_rate_after_autoreply = (
        autoreplied.filter(reopened_count__gt=0).count() / autoreplied.count()
        if autoreplied.count()
        else None
    )

    decisions = ReviewDecision.objects.filter(decided_at__gte=since)
    total_decisions = decisions.count()
    overrides = decisions.exclude(action_taken="approve").count()
    override_rate = overrides / total_decisions if total_decisions else None

    reroutes = decisions.filter(action_taken="reroute").count()
    reroute_rate = reroutes / total_decisions if total_decisions else None

    routed = RoutingDecision.objects.filter(decided_at__gte=since)
    total_routed = routed.count()
    refused = routed.filter(reason_code="retrieval_below_floor").count()
    refusal_rate = refused / total_routed if total_routed else None

    quote_caught = routed.filter(
        reason_code__in=["quote_invalid", "quote_source_not_in_topk", "negation_mismatch"]
    ).count()
    autoreply_attempts = routed.filter(
        branch__in=["auto_reply", "hitl"], gate_failed__isnull=True
    ).count()

    override_by_category = list(
        decisions.exclude(action_taken="approve")
        .values("review_item__ticket__category")
        .annotate(n=Count("id"))
        .order_by("-n")
    )

    return {
        "reopen_rate_after_autoreply": reopen_rate_after_autoreply,
        "override_rate": override_rate,
        "override_rate_by_category": override_by_category,
        "reroute_rate": reroute_rate,
        "refusal_rate": refusal_rate,
        "hallucination_catch_rate": (quote_caught / autoreply_attempts) if autoreply_attempts else None,
    }


def hitl_health_metrics(window_days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=window_days)

    queue_depth = list(
        ReviewItem.objects.filter(state="pending").values("queue").annotate(n=Count("id"))
    )

    resolved = ReviewItem.objects.filter(state="resolved", created_at__gte=since, decisions__isnull=False)
    wait_times = [
        (d.decided_at - ri.created_at).total_seconds()
        for ri in resolved.prefetch_related("decisions")
        for d in [ri.decisions.order_by("decided_at").first()]
        if d
    ]

    per_reviewer_counts = list(
        ReviewDecision.objects.filter(decided_at__gte=since)
        .values("reviewer_id", "reviewer__username")
        .annotate(total=Count("id"), approved=Count("id", filter=Q(action_taken="approve")))
    )
    # Median needs a per-group percentile, which the ORM can't express
    # portably — computed in Python from the raw (reviewer_id, seconds)
    # pairs instead of a second query per reviewer.
    times_by_reviewer: dict[int, list[float]] = {}
    for reviewer_id, seconds in ReviewDecision.objects.filter(decided_at__gte=since).values_list(
        "reviewer_id", "time_spent_sec"
    ):
        times_by_reviewer.setdefault(reviewer_id, []).append(seconds)

    per_reviewer = []
    for row in per_reviewer_counts:
        row["approve_rate"] = row["approved"] / row["total"] if row["total"] else None
        row["median_time_spent_sec"] = _percentile(times_by_reviewer.get(row["reviewer_id"], []), 0.5)
        per_reviewer.append(row)

    return {
        "queue_depth_by_queue": queue_depth,
        "time_in_queue_p50_sec": _percentile(wait_times, 0.5),
        "time_in_queue_p95_sec": _percentile(wait_times, 0.95),
        "approve_rate_per_reviewer": per_reviewer,
    }


def ops_metrics(window_days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=window_days)
    runs = AiRun.objects.filter(created_at__gte=since)
    latencies = list(runs.exclude(latency_ms__isnull=True).values_list("latency_ms", flat=True))
    total_runs = runs.count()
    degraded_runs = runs.exclude(degraded_reason__isnull=True).count()
    total_cost = sum((r.cost_usd or 0) for r in runs.only("cost_usd"))
    total_tickets = Ticket.objects.filter(created_at__gte=since).count()

    return {
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "cost_per_ticket_usd": float(total_cost) / total_tickets if total_tickets else None,
        "degraded_run_ratio": degraded_runs / total_runs if total_runs else None,
        "circuit_open_events": runs.filter(degraded_reason="circuit_open").count(),
    }


def business_metrics(window_days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=window_days)
    routed = RoutingDecision.objects.filter(decided_at__gte=since)
    total = routed.count()
    automated = routed.filter(branch__in=["auto_reply", "auto_route"]).count()

    tickets = Ticket.objects.filter(created_at__gte=since, sla_due_at__isnull=False)
    total_sla = tickets.count()
    met_sla = tickets.filter(resolved_at__isnull=False, resolved_at__lte=F("sla_due_at")).count()

    return {
        "automation_rate": automated / total if total else None,
        "sla_compliance": met_sla / total_sla if total_sla else None,
    }


def dashboard_summary(window_days: int = 30) -> dict:
    return {
        "quality": quality_metrics(window_days),
        "hitl_health": hitl_health_metrics(window_days),
        "ops": ops_metrics(min(window_days, 7)),
        "business": business_metrics(window_days),
    }
