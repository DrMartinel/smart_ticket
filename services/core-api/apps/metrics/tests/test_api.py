# pyright: standard
"""
The dashboard over HTTP. Most of its numbers are None on a quiet window (no
decisions, no runs), and the response schema must allow that: a field typed
too strictly turns an empty dashboard into a 500.
"""

import pytest

from contracts.enums import ReviewAction

from apps.review.models import ReviewDecision
from apps.review.tests.test_decide import review_item

GROUPS = {
    "quality": {
        "reopen_rate_after_autoreply",
        "override_rate",
        "override_rate_by_category",
        "reroute_rate",
        "refusal_rate",
        "hallucination_catch_rate",
    },
    "hitl_health": {
        "queue_depth_by_queue",
        "time_in_queue_p50_sec",
        "time_in_queue_p95_sec",
        "approve_rate_per_reviewer",
    },
    "ops": {
        "latency_p50_ms",
        "latency_p95_ms",
        "cost_per_ticket_usd",
        "degraded_run_ratio",
        "circuit_open_events",
    },
    "business": {"automation_rate", "sla_compliance"},
}


@pytest.mark.django_db
def test_an_empty_window_still_returns_every_metric(manager_user, api_as):
    response = api_as(manager_user).get("/api/metrics/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert {group: set(values) for group, values in body.items()} == GROUPS
    assert body["quality"]["override_rate"] is None
    assert body["hitl_health"]["approve_rate_per_reviewer"] == []


@pytest.mark.django_db
def test_per_reviewer_and_per_category_rows(employee_user, technician_user, manager_user, api_as):
    item = review_item(employee_user)
    ReviewDecision.objects.create(
        review_item=item,
        reviewer=technician_user,
        action_taken=ReviewAction.REROUTE.value,
        override_reason="wrong team",
        time_spent_sec=40,
    )

    body = api_as(manager_user).get("/api/metrics/dashboard").json()

    [reviewer] = body["hitl_health"]["approve_rate_per_reviewer"]
    assert set(reviewer) == {
        "reviewer_id",
        "reviewer__username",
        "total",
        "approved",
        "approve_rate",
        "median_time_spent_sec",
    }
    assert reviewer["reviewer__username"] == "tech"
    assert [set(row) for row in body["quality"]["override_rate_by_category"]] == [
        {"review_item__ticket__category", "n"}
    ]
