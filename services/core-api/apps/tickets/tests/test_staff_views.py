"""The staff ticket list and detail: who may see them, what each view holds, and what a row carries."""

import pytest

from apps.lifecycle.tests.conftest import make_ticket
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.review.models import ReviewItem
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def test_a_requester_cannot_list_tickets(api_as, employee_user):
    assert api_as(employee_user).get("/api/tickets").status_code == 403


def test_each_view_holds_its_tickets_and_reports_every_count(
    api_as, employee_user, technician_user
):
    waiting = make_ticket(employee_user)
    ReviewItem.objects.create(ticket=waiting, queue="low_confidence", priority=2)
    mine = make_ticket(employee_user)
    Ticket.objects.filter(pk=mine.pk).update(assigned_to=technician_user)
    done = make_ticket(employee_user, at=PipelineStatus.AUTO_REPLIED)

    client = api_as(technician_user)
    ids = {
        view: [r["public_id"] for r in client.get(f"/api/tickets?view={view}").json()["items"]]
        for view in ("review", "mine", "open", "resolved", "all")
    }

    assert ids["review"] == [waiting.public_id]
    assert ids["mine"] == [mine.public_id]
    assert done.public_id not in ids["open"] and done.public_id in ids["resolved"]
    assert set(ids["all"]) == {waiting.public_id, mine.public_id, done.public_id}
    counts = client.get("/api/tickets").json()["counts"]
    assert counts == {"review": 1, "mine": 1, "open": 2, "resolved": 1, "all": 3}


def test_a_row_carries_status_review_and_people(api_as, employee_user, technician_user):
    ticket = make_ticket(employee_user)
    ReviewItem.objects.create(ticket=ticket, queue="injection", priority=1)

    [row] = api_as(technician_user).get("/api/tickets").json()["items"]

    assert row["status"]["key"] == "pending_review"
    assert row["status"]["name"] == "Pending review"
    assert row["review"]["queue"] == "injection"
    assert row["reporter"] == employee_user.username
    assert row["assignee"] is None


def test_search_matches_the_id_or_the_subject(api_as, employee_user, technician_user):
    ticket = make_ticket(employee_user)
    make_ticket(employee_user)
    client = api_as(technician_user)

    by_id = client.get(f"/api/tickets?q={ticket.public_id[-4:]}").json()["items"]
    by_subject = client.get("/api/tickets?q=vpn drops").json()["items"]

    assert [r["public_id"] for r in by_id] == [ticket.public_id]
    assert len(by_subject) == 2


def test_paging_splits_the_view(api_as, employee_user, technician_user):
    for _ in range(3):
        make_ticket(employee_user)

    page = api_as(technician_user).get("/api/tickets?limit=2&page=2").json()

    assert page["total"] == 3
    assert len(page["items"]) == 1


def test_the_detail_explains_a_ticket_with_no_ai_run(api_as, employee_user, technician_user):
    ticket = make_ticket(employee_user)

    body = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/detail").json()

    assert body["ai"] is None
    assert body["routing"] == []
    assert body["reporter_person"]["username"] == employee_user.username


def test_the_detail_summarises_the_latest_ai_run(api_as, employee_user, technician_user):
    from apps.kb.models import KbArticle
    from apps.tickets.models import AiRun

    ticket = make_ticket(employee_user)
    KbArticle.objects.create(
        slug="iam.reset", title="Reset an access portal password", body="x", category="access"
    )
    AiRun.objects.create(
        ticket=ticket,
        idempotency_key=f"{ticket.id}:1",
        prompt_version="t",
        model="t",
        graph_version="t",
        proposed_draft={
            "proposed_intent": "auto_reply",
            "kb_slug": "iam.reset",
            "answer_draft": "Use the reset link.",
            "verbatim_quote": "Choose Forgot password.",
        },
        trust_signals={
            "classification": {"category_choice": "access", "category_confidence": 0.91},
            "policy": {"injection_detected": True},
        },
        trust_score="0.8125",
        degraded_reason="rerank_low_confidence",
    )

    ai = api_as(technician_user).get(f"/api/tickets/{ticket.public_id}/detail").json()["ai"]

    assert ai["proposed_intent"] == "auto_reply"
    assert (ai["category"], ai["category_confidence"]) == ("access", 0.91)
    assert ai["kb_title"] == "Reset an access portal password"
    assert ai["trust_score"] == 0.8125
    assert ai["degraded_reason"] == "rerank_low_confidence"
    assert ai["injection_detected"] is True


def test_a_requester_cannot_read_the_detail_or_assign(api_as, employee_user):
    ticket = make_ticket(employee_user)
    client = api_as(employee_user)

    detail = client.get(f"/api/tickets/{ticket.public_id}/detail")
    assign = client.post(
        f"/api/tickets/{ticket.public_id}/reassign",
        {"reason_code": "workload", "note": "trying to grab it", "expected_version": 0},
        content_type="application/json",
    )

    assert detail.status_code == assign.status_code == 403


def test_security_can_list_open_and_board_tickets(api_as, employee_user, security_user):
    """Security works review queues (injection, pii_verify), so the staff ticket views admit it."""
    from apps.lifecycle.models import Workflow

    ticket = make_ticket(employee_user)
    client = api_as(security_user)
    workflow = Workflow.objects.get(is_default=True)

    assert client.get("/api/tickets").status_code == 200
    assert client.get(f"/api/tickets/{ticket.public_id}/detail").status_code == 200
    assert client.get(f"/api/tickets/board?workflow={workflow.id}").status_code == 200


def test_the_detail_loads_its_lists_in_a_fixed_number_of_queries(
    api_as, employee_user, technician_user, django_assert_max_num_queries
):
    from apps.tickets.models import AiRun

    ticket = make_ticket(employee_user)
    for n in range(3):
        ReviewItem.objects.create(ticket=ticket, queue="low_confidence")
        AiRun.objects.create(
            ticket=ticket,
            idempotency_key=f"{ticket.id}:{n}",
            prompt_version="t",
            model="t",
            graph_version="t",
            trust_signals={},
        )
    client = api_as(technician_user)

    with django_assert_max_num_queries(12):
        assert client.get(f"/api/tickets/{ticket.public_id}/detail").status_code == 200
