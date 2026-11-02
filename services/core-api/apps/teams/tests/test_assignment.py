"""Assignment at handoff, take and reassign: team from category, person by strategy (F2)."""

from __future__ import annotations

import json
import threading

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.lifecycle.tests.conftest import make_ticket
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.notifications.models import Message
from apps.review.models import EvalCandidate, ReviewItem
from apps.teams.models import Reassignment, Team, TeamCategory, TeamMembership
from apps.teams.tests.conftest import handed_off
from apps.teams.utils.assignment import Assignment, assignment
from apps.teams.utils.vocabulary import AssignmentTrigger
from apps.tickets.models import RoutingDecision as DecisionRow
from apps.tickets.models import Ticket
from apps.tickets.utils.pipeline import _execute_or_enqueue
from apps.tickets.utils.router import Branch, ReasonCode, ReviewQueue, RoutingDecision
from infrastructure.dtos import TicketCategory

JSON = "application/json"


def auto_route(ticket: Ticket, category: TicketCategory) -> None:
    """Carries out a live auto_route decision for `ticket`, as the pipeline does."""
    decision = RoutingDecision(
        branch=Branch.AUTO_ROUTE, reason_code=ReasonCode.ALL_CHECKS_PASSED, category=category
    )
    _execute_or_enqueue(ticket, None, decision, False, None)


def notices(user, event: str) -> list[Message]:
    return list(Message.objects.filter(user=user, event=event, channel="in_app"))


def post(client, url: str, body: dict):
    return client.post(url, json.dumps(body), content_type=JSON)


# ── at handoff ──


def test_auto_route_assigns_team_from_router_category(network):
    """AC-F2-01: the least-loaded eligible member, the router's category, a notice."""
    ticket = handed_off(network.people["lan"], public_id="TKT-2026-000415")
    row = DecisionRow.objects.create(
        ticket=ticket,
        branch="auto_route",
        reason_code="all_checks_passed",
        reason_detail="x",
        thresholds_used={},
        shadow_mode=False,
    )

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert (ticket.status, ticket.team, ticket.assigned_team) == (
        "auto_routed",
        network.team,
        "network",
    )
    assert ticket.assigned_to == network.people["khoa"]
    assert notices(network.people["khoa"], "ticket.assigned")
    (audit,) = AuditLog.objects.filter(event="ticket_assigned")
    assert audit.payload["strategy"] == "least_loaded"
    assert audit.payload["candidates"] == 2
    assert DecisionRow.objects.get(pk=row.pk).branch == "auto_route"


def test_assignment_never_changes_routing_decision(network):
    """BR-F2-02: the decision row and the ticket's status are what routing made them."""
    ticket = handed_off(network.people["lan"])
    row = DecisionRow.objects.create(
        ticket=ticket,
        branch="auto_route",
        reason_code="all_checks_passed",
        reason_detail="x",
        thresholds_used={"t": 1},
        shadow_mode=False,
    )
    before = DecisionRow.objects.filter(pk=row.pk).values().get()

    auto_route(ticket, TicketCategory.NETWORK)

    assert DecisionRow.objects.filter(pk=row.pk).values().get() == before
    assert DecisionRow.objects.count() == 1


def test_no_eligible_member_leaves_unassigned_and_notifies_lead(network):
    """AC-F2-02."""
    TeamMembership.objects.filter(team=network.team).update(is_available=False)
    ticket = handed_off(network.people["lan"])

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert (ticket.team, ticket.assigned_to) == (network.team, None)
    assert notices(network.people["duc"], "ticket.unassigned")


def test_an_unowned_category_goes_to_the_fallback_team(network):
    """AC-F2-07: still auto_routed, on the fallback team, assignment_failed audited."""
    TeamCategory.objects.filter(category="software").delete()
    ticket = handed_off(network.people["lan"])

    auto_route(ticket, TicketCategory.SOFTWARE)

    ticket.refresh_from_db()
    assert ticket.status == "auto_routed"
    assert ticket.team == Team.objects.get(is_fallback=True)
    (failed,) = AuditLog.objects.filter(event="assignment_failed")
    assert failed.payload["reason"] == "no_team_for_category"


def test_an_assignment_error_keeps_the_status_and_is_audited(network, monkeypatch):
    """BR-X-07: an error rolls back the assignment only."""

    def broken(self, team):
        raise RuntimeError("membership table unreadable")

    monkeypatch.setattr(Assignment, "pick", broken)
    ticket = handed_off(network.people["lan"])

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert (ticket.status, ticket.team, ticket.assigned_to) == ("auto_routed", None, None)
    (failed,) = AuditLog.objects.filter(event="assignment_failed")
    assert failed.payload["reason"] == "error"


def test_shadow_mode_assigns_nothing_until_a_review(network, settings):
    ticket = handed_off(network.people["lan"])
    decision = RoutingDecision(
        branch=Branch.AUTO_ROUTE,
        reason_code=ReasonCode.ALL_CHECKS_PASSED,
        category=TicketCategory.NETWORK,
    )

    _execute_or_enqueue(ticket, None, decision, True, None)

    ticket.refresh_from_db()
    assert (ticket.team, ticket.assigned_to) == (None, None)


def test_round_robin_picks_the_member_assigned_longest_ago(network):
    network.team.strategy = "round_robin"
    network.team.save(update_fields=["strategy"])
    TeamMembership.objects.filter(user=network.people["duc"]).update(last_assigned_at=None)
    ticket = handed_off(network.people["lan"])

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert ticket.assigned_to == network.people["duc"]


def test_a_full_member_is_skipped(network):
    network.team.max_open_per_member = 4
    network.team.save(update_fields=["max_open_per_member"])
    ticket = handed_off(network.people["lan"])

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert ticket.assigned_to is None


def test_a_duplicate_goes_to_the_originals_assignee_when_eligible(network):
    original = handed_off(network.people["lan"], assigned_to=network.people["duc"])
    ticket = handed_off(network.people["lan"], duplicate_of=original)

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert ticket.assigned_to == network.people["duc"]


def test_a_duplicate_of_someone_on_leave_goes_by_strategy(network):
    original = handed_off(network.people["lan"], assigned_to=network.people["nam"])
    ticket = handed_off(network.people["lan"], duplicate_of=original)

    auto_route(ticket, TicketCategory.NETWORK)

    ticket.refresh_from_db()
    assert ticket.assigned_to == network.people["khoa"]


# ── review decisions ──


def review_item(network, **ticket_fields) -> ReviewItem:
    ticket = handed_off(network.people["lan"], public_id="TKT-2026-000415", **ticket_fields)
    return ReviewItem.objects.create(ticket=ticket, queue=ReviewQueue.LOW_CONFIDENCE.value)


def test_review_reroute_sets_category_and_eval_candidate(network, api_as):
    """AC-F2-03: the reviewer's category wins, the access team gets it, one reroute label."""
    item = review_item(network, category="network")

    response = post(
        api_as(network.people["ha"]),
        f"/api/review/items/{item.id}/decide",
        {
            "action_taken": "reroute",
            "category_verdict": "wrong",
            "corrected_category": "access",
            "override_reason": "Tài khoản bị khoá, không phải lỗi VPN",
            "time_spent_sec": 40,
        },
    )

    assert response.status_code == 200
    ticket = Ticket.objects.get(pk=item.ticket_id)
    assert (ticket.category, ticket.assigned_team) == ("access", "access")
    assert ticket.assigned_to == network.people["ha"]
    (label,) = EvalCandidate.objects.filter(ticket=ticket)
    assert label.source == "reroute"
    assert label.ai_prediction == {"category": "network"}


def test_an_approval_assigns_by_the_routers_category(network, api_as):
    item = review_item(network, category="network")

    post(
        api_as(network.people["ha"]),
        f"/api/review/items/{item.id}/decide",
        {"action_taken": "approve", "time_spent_sec": 10},
    )

    ticket = Ticket.objects.get(pk=item.ticket_id)
    assert (ticket.assigned_team, ticket.assigned_to) == ("network", network.people["khoa"])
    assert not EvalCandidate.objects.exists()


def test_an_approval_with_no_category_goes_to_the_fallback_team(network, api_as):
    item = review_item(network)

    post(
        api_as(network.people["ha"]),
        f"/api/review/items/{item.id}/decide",
        {"action_taken": "approve", "time_spent_sec": 10},
    )

    ticket = Ticket.objects.get(pk=item.ticket_id)
    assert ticket.team == Team.objects.get(is_fallback=True)
    assert AuditLog.objects.get(event="assignment_failed").payload["reason"] == "no_category"


def test_a_rejection_assigns_nobody(network, api_as):
    item = review_item(network, category="network")

    post(
        api_as(network.people["ha"]),
        f"/api/review/items/{item.id}/decide",
        {"action_taken": "reject", "override_reason": "spam", "time_spent_sec": 5},
    )

    assert Ticket.objects.get(pk=item.ticket_id).team is None


# ── take ──


def queued(network) -> Ticket:
    ticket = handed_off(network.people["lan"], category="network")
    TeamMembership.objects.filter(team=network.team).update(is_available=False)
    auto_route(ticket, TicketCategory.NETWORK)
    TeamMembership.objects.filter(team=network.team).exclude(user=network.people["vy"]).update(
        is_available=True
    )
    ticket.refresh_from_db()
    assert ticket.assigned_to is None
    return ticket


def test_two_takes_one_winner(network, api_as):
    """AC-F2-06."""
    ticket = queued(network)
    url = f"/api/tickets/{ticket.public_id}/take"

    first = post(api_as(network.people["khoa"]), url, {"expected_version": ticket.version})
    second = post(api_as(network.people["duc"]), url, {"expected_version": ticket.version})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "already_assigned"
    assert Ticket.objects.get(pk=ticket.pk).assigned_to == network.people["khoa"]


def test_someone_outside_the_team_cannot_take(network, api_as):
    ticket = queued(network)

    response = post(
        api_as(network.people["ha"]),
        f"/api/tickets/{ticket.public_id}/take",
        {"expected_version": ticket.version},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "not_a_member"


def test_a_ticket_held_by_someone_unavailable_can_be_taken(network, api_as):
    ticket = handed_off(network.people["lan"], category="network")
    auto_route(ticket, TicketCategory.NETWORK)
    TeamMembership.objects.filter(user=network.people["khoa"]).update(is_available=False)
    ticket.refresh_from_db()

    response = post(
        api_as(network.people["duc"]),
        f"/api/tickets/{ticket.public_id}/take",
        {"expected_version": ticket.version},
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == "duc.tm"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_assignments_balance(network):
    """BR-F2-08: two handoffs at once, one lock, two different people."""
    tickets = [handed_off(network.people["lan"]) for _ in range(2)]
    Ticket.objects.filter(assigned_to__in=[network.people["duc"], network.people["khoa"]]).update(
        assigned_to=None
    )
    errors: list[BaseException] = []

    def run(ticket: Ticket) -> None:
        try:
            ticket = Ticket.objects.get(pk=ticket.pk)
            assignment.assign_after_handoff(
                ticket, AssignmentTrigger.AUTO_ROUTE, category="network"
            )
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(t,)) for t in tickets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    owners = {Ticket.objects.get(pk=t.pk).assigned_to_id for t in tickets}
    assert owners == {network.people["duc"].id, network.people["khoa"].id}


# ── reassign ──


def reassign(client, ticket: Ticket, **body):
    ticket.refresh_from_db()
    return post(
        client,
        f"/api/tickets/{ticket.public_id}/reassign",
        {"expected_version": ticket.version, **body},
    )


def assigned(network) -> Ticket:
    ticket = handed_off(network.people["lan"], public_id="TKT-2026-000415", category="network")
    auto_route(ticket, TicketCategory.NETWORK)
    ticket.refresh_from_db()
    assert ticket.assigned_to == network.people["khoa"]
    return ticket


def test_reassign_needs_a_reason(network, api_as):
    """AC-F2-04."""
    ticket = assigned(network)

    response = reassign(
        api_as(network.people["khoa"]), ticket, to_team="access", reason_code="wrong_team"
    )

    assert response.status_code == 422
    assert response.json()["code"] == "reason_required"


def test_a_member_cannot_move_a_ticket_out_of_the_team(network, api_as):
    """AC-F2-05."""
    ticket = assigned(network)

    response = reassign(
        api_as(network.people["khoa"]),
        ticket,
        to_team="hardware",
        reason_code="wrong_team",
        note="Màn hình không lên, phải là phần cứng",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "lead_required"


def test_the_lead_moves_a_ticket_to_another_team_and_category(network, api_as):
    """Spec §g reassignment record: masked note, new team's person, a reroute label."""
    ticket = assigned(network)

    response = reassign(
        api_as(network.people["duc"]),
        ticket,
        to_team="access",
        reason_code="wrong_team",
        note="VPN kết nối được, tài khoản lan.nt@congty.vn bị khoá trên Identity Center",
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["team"], body["assigned_to"], body["category"]) == ("access", "ha.vt", "access")
    assert body["last_reassignment"]["note_masked"] == (
        "VPN kết nối được, tài khoản [EMAIL_1] bị khoá trên Identity Center"
    )
    row = Reassignment.objects.get(ticket=ticket)
    assert (row.from_user, row.to_user) == (network.people["khoa"], network.people["ha"])
    assert (row.from_category, row.to_category) == ("network", "access")
    label = EvalCandidate.objects.get(ticket=ticket, source="reroute")
    assert label.human_truth == {"category": "access", "reason_code": "wrong_team"}
    assert notices(network.people["ha"], "ticket.reassigned")
    assert notices(network.people["khoa"], "ticket.reassigned")


def test_the_assignee_hands_over_within_the_team(network, api_as):
    ticket = assigned(network)

    response = reassign(
        api_as(network.people["khoa"]),
        ticket,
        to_user="duc.tm",
        reason_code="skill",
        note="Anh Đức rành Cisco AnyConnect hơn",
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == "duc.tm"
    assert AuditLog.objects.filter(event="ticket_reassigned").count() == 1


def test_reassigning_to_someone_outside_the_target_team_is_refused(network, api_as):
    ticket = assigned(network)

    response = reassign(
        api_as(network.people["duc"]),
        ticket,
        to_user="ha.vt",
        reason_code="skill",
        note="Chuyển cho Hà xử lý",
    )

    assert response.json()["code"] == "user_not_in_team"


def test_a_stale_version_is_refused(network, api_as):
    ticket = assigned(network)

    response = post(
        api_as(network.people["huy"]),
        f"/api/tickets/{ticket.public_id}/reassign",
        {
            "to_user": "duc.tm",
            "reason_code": "workload",
            "note": "Cân bằng tải trong nhóm",
            "expected_version": ticket.version - 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


def test_security_staff_touch_security_tickets_only(network, api_as):
    ticket = assigned(network)

    response = reassign(
        api_as(network.people["anh"]),
        ticket,
        to_user="duc.tm",
        reason_code="other",
        note="Không phải việc của nhóm bảo mật",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "not_allowed"


def test_a_resolved_ticket_is_not_reassigned(network, api_as):
    ticket = make_ticket(network.people["lan"], at=PipelineStatus.AUTO_REPLIED)
    ticket.team = network.team
    ticket.save(update_fields=["team"])

    response = reassign(
        api_as(network.people["huy"]),
        ticket,
        to_user="duc.tm",
        reason_code="other",
        note="Mở lại để xem",
    )

    assert response.json()["code"] == "ticket_completed"


# ── the assign_team action ──


def test_assign_team_refuses_an_unknown_slug_when_saved(network):
    """FR-F2-014."""
    from apps.lifecycle.models import Workflow
    from apps.lifecycle.utils.actions import HANDLERS
    from apps.lifecycle.utils.vocabulary import ActionCode

    handler = HANDLERS[ActionCode.ASSIGN_TEAM]
    workflow = Workflow.objects.default()

    assert handler.config_errors({"team": "vendor-desk"}, workflow) == [
        "no active team 'vendor-desk'"
    ]
    assert handler.config_errors({"team": "network", "pick_member": True}, workflow) == []


def test_assign_team_picks_a_member_when_asked(network):
    ticket = handed_off(network.people["lan"])

    assignment.move_to_team(ticket, network.team, pick_member=True)

    ticket.refresh_from_db()
    assert (ticket.assigned_team, ticket.assigned_to) == ("network", network.people["khoa"])


def test_assign_team_keeps_the_assignee_otherwise(network):
    ticket = handed_off(network.people["lan"], assigned_to=network.people["vy"])

    assignment.move_to_team(ticket, network.team, pick_member=False)

    ticket.refresh_from_db()
    assert (ticket.team, ticket.assigned_to) == (network.team, network.people["vy"])
