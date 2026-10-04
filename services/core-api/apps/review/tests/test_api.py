"""
Review endpoints over HTTP. The review item is the richest response: fields
from the ticket, from the AI run, and a trust breakdown computed at read
time. A review item with no AI run (a mask_failed ticket never reached the
model) must still load, with every AI field null; if the schema gets that
wrong, the item cannot be opened at all.
"""

import pytest

from apps.tickets.utils.patterns import PIILevel
from apps.review.models import ReviewAction, ReviewItem
from apps.tickets.utils.router import ReviewQueue

from apps.review.tests.test_decide import review_item
from apps.tickets.models import AiRun, RoutingDecision, Ticket

ITEM_KEYS = {
    "id",
    "ticket_public_id",
    "subject_masked",
    "body_masked",
    "queue",
    "priority",
    "state",
    "claimed_by",
    "created_at",
    "ai_run_id",
    "trust_signals",
    "trust_score",
    "trust_contributions",
    "proposed_draft",
    "routing_decisions",
}
SIGNALS = {
    "retrieval": {
        "rerank_top1": 0.9,
        "rerank_margin": 0.2,
        "docs_above_floor": 2,
    },
    "generation": {
        "quote_match_ratio": 1.0,
        "quote_source_in_topk": True,
        "negation_consistent": True,
        "quote_applicable": True,
        "clarify_options_in_topk": False,
    },
    "policy": {
        "kb_auto_reply_allowed": True,
        "kb_risk_tier": "low",
        "pii_level": "routine",
        "injection_detected": False,
        "mass_incident": False,
    },
    "classification": {"category_choice": "access", "category_confidence": 0.9},
}


def scored_item(reporter) -> ReviewItem:
    item = review_item(reporter)
    assert item.ai_run is not None
    AiRun.objects.filter(id=item.ai_run.id).update(trust_signals=SIGNALS, trust_score="0.8123")
    RoutingDecision.objects.create(
        ticket=item.ticket,
        ai_run=item.ai_run,
        branch="hitl",
        reason_code="trust_below_auto_threshold",
        reason_detail="below t_auto",
        thresholds_used={},
    )
    return item


def unscored_item(reporter) -> ReviewItem:
    ticket = Ticket.objects.create(
        public_id="TKT-REVIEW-002",
        reporter=reporter,
        subject_masked="s",
        body_masked="b",
        pii_level=PIILevel.MASK_FAILED.value,
    )
    return ReviewItem.objects.create(
        ticket=ticket, ai_run=None, queue=ReviewQueue.MASK_FAILED.value, priority=1
    )


@pytest.mark.django_db
def test_an_item_with_an_ai_run(employee_user, technician_user, api_as):
    item = scored_item(employee_user)

    body = api_as(technician_user).get(f"/api/review/items/{item.id}").json()

    assert set(body) == ITEM_KEYS
    assert body["ticket_public_id"] == "TKT-REVIEW-001"
    assert body["trust_score"] == 0.8123
    assert body["trust_contributions"] and all(
        isinstance(v, float) for v in body["trust_contributions"].values()
    )
    [decision] = body["routing_decisions"]
    assert set(decision) == {"branch", "reason_code", "reason_detail", "gate_failed", "shadow_mode"}


@pytest.mark.django_db
def test_an_item_without_an_ai_run_still_loads(employee_user, technician_user, api_as):
    item = unscored_item(employee_user)

    response = api_as(technician_user).get(f"/api/review/items/{item.id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == ITEM_KEYS
    for field in (
        "ai_run_id",
        "trust_signals",
        "trust_score",
        "trust_contributions",
        "proposed_draft",
    ):
        assert body[field] is None
    assert body["routing_decisions"] == []


@pytest.mark.django_db
def test_the_queue_lists_items_most_urgent_first(employee_user, technician_user, api_as):
    scored_item(employee_user)
    unscored_item(employee_user)

    rows = api_as(technician_user).get("/api/review/queue").json()

    assert [row["priority"] for row in rows] == [1, 3]
    assert all(set(row) == ITEM_KEYS for row in rows)


@pytest.mark.django_db
def test_claim_returns_the_item_with_its_claimant(employee_user, technician_user, api_as):
    item = review_item(employee_user)

    response = api_as(technician_user).post(f"/api/review/items/{item.id}/claim")

    assert response.status_code == 200
    assert response.json()["claimed_by"] == str(technician_user.id)


@pytest.mark.django_db
def test_decide_returns_the_decision(employee_user, technician_user, api_as):
    item = review_item(employee_user)

    response = api_as(technician_user).post(
        f"/api/review/items/{item.id}/decide",
        {"action_taken": ReviewAction.APPROVE.value, "time_spent_sec": 20},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert set(response.json()) == {"id", "action_taken"}
    assert response.json()["action_taken"] == "approve"
