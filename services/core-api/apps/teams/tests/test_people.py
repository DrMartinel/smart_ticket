"""Availability, leave, the team queue and workload, and team configuration (F2)."""

from __future__ import annotations

import json
from datetime import timedelta

from apps.accounts.models import AuthSource
from apps.audit.models import AuditLog
from apps.teams.models import Leave, Team, TeamCategory, TeamMembership
from apps.teams.tests.conftest import handed_off, person
from apps.teams.utils.assignment import today
from apps.tickets.models import Ticket

JSON = "application/json"


def send(client, method: str, url: str, body: dict | None = None):
    return getattr(client, method)(url, json.dumps(body or {}), content_type=JSON)


# ── availability and leave ──


def test_going_unavailable_moves_nothing(network, api_as):
    """AC-F2-08: vy.tt keeps her 3 tickets; the lead sees them flagged."""
    TeamMembership.objects.filter(user=network.people["vy"]).update(is_available=True)

    response = send(
        api_as(network.people["vy"]), "put", "/api/me/availability", {"is_available": False}
    )

    assert response.status_code == 200
    assert Ticket.objects.filter(assigned_to=network.people["vy"]).count() == 3
    rows = {
        r["user"]: r
        for r in api_as(network.people["duc"]).get("/api/teams/network/workload").json()
    }
    assert rows["vy.tt"] == {**rows["vy.tt"], "available": False, "open": 3, "flagged": True}
    assert AuditLog.objects.filter(event="availability_changed").count() == 1


def test_a_member_sees_only_their_own_workload_row(network, api_as):
    rows = api_as(network.people["khoa"]).get("/api/teams/network/workload").json()

    assert [r["user"] for r in rows] == ["khoa.lv"]


def test_someone_outside_the_team_sees_no_workload(network, api_as):
    response = api_as(network.people["ha"]).get("/api/teams/network/workload")

    assert response.status_code == 403
    assert response.json()["code"] == "not_a_member"


def test_leave_today_makes_a_member_ineligible_and_is_shown(network, api_as):
    rows = {
        r["user"]: r
        for r in api_as(network.people["huy"]).get("/api/teams/network/workload").json()
    }

    assert rows["nam.pt"]["on_leave"] is True
    assert rows["nam.pt"]["flagged"] is True
    assert rows["khoa.lv"]["on_leave"] is False


def test_a_leave_ending_before_it_starts_is_refused(network, api_as):
    response = send(
        api_as(network.people["khoa"]),
        "post",
        "/api/me/leaves",
        {"starts_on": str(today()), "ends_on": str(today() - timedelta(days=1))},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "bad_dates"


def test_a_lead_adds_leave_for_a_member_and_the_note_is_masked(network, api_as):
    response = send(
        api_as(network.people["duc"]),
        "post",
        "/api/me/leaves",
        {
            "starts_on": str(today()),
            "ends_on": str(today()),
            "note": "Nghỉ ốm, gọi 0912345678",
            "user": "khoa.lv",
        },
    )

    assert response.status_code == 201
    leave = Leave.objects.get(user=network.people["khoa"])
    assert "0912345678" not in leave.note
    assert AuditLog.objects.filter(event="leave_changed").count() == 1


def test_a_member_cannot_add_leave_for_someone_else(network, api_as):
    response = send(
        api_as(network.people["khoa"]),
        "post",
        "/api/me/leaves",
        {"starts_on": str(today()), "ends_on": str(today()), "user": "vy.tt"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "lead_required"


def test_my_availability_lists_teams_and_leave(network, api_as):
    body = api_as(network.people["nam"]).get("/api/me/availability").json()

    assert [m["team"] for m in body["memberships"]] == ["network"]
    assert len(body["leaves"]) == 1


# ── the team queue ──


def test_the_queue_lists_unowned_tickets_first(network, api_as):
    owned = handed_off(network.people["lan"], team=network.team, assigned_to=network.people["khoa"])
    unowned = handed_off(network.people["lan"], team=network.team)

    items = api_as(network.people["khoa"]).get("/api/teams/network/queue").json()["items"]

    ids = [i["public_id"] for i in items]
    assert ids.index(unowned.public_id) < ids.index(owned.public_id)
    unassigned = api_as(network.people["khoa"]).get("/api/teams/network/queue?unassigned=true")
    assert [i["public_id"] for i in unassigned.json()["items"]] == [unowned.public_id]


def test_the_queue_is_for_the_team(network, api_as):
    response = api_as(network.people["ha"]).get("/api/teams/network/queue")

    assert response.status_code == 403


# ── team configuration ──


def test_a_category_owned_elsewhere_is_refused(network, api_as):
    """UC-F2-06 1x."""
    response = send(
        api_as(network.people["huy"]),
        "patch",
        "/api/teams/access",
        {"categories": ["access", "network"], "reason": "Access nhận cả mạng"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "category_taken"


def test_a_category_left_without_a_team_is_refused(network, api_as):
    """UC-F2-06 1y."""
    response = send(
        api_as(network.people["huy"]),
        "patch",
        "/api/teams/network",
        {"categories": [], "reason": "Giải thể nhóm mạng"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "category_unowned"
    assert TeamCategory.objects.get(category="network").team == network.team


def test_a_category_moves_when_asked_and_is_audited(network, api_as):
    response = send(
        api_as(network.people["huy"]),
        "patch",
        "/api/teams/access",
        {"categories": ["access", "network"], "move_categories": True, "reason": "Gộp nhóm"},
    )

    assert response.status_code == 200
    assert TeamCategory.objects.get(category="network").team.slug == "access"
    (audit,) = AuditLog.objects.filter(event="team_changed")
    assert audit.payload["before"]["categories"] == ["access"]
    assert audit.payload["after"]["categories"] == ["access", "network"]


def test_a_team_change_needs_a_reason(network, api_as):
    response = send(api_as(network.people["huy"]), "patch", "/api/teams/network", {"name": "Net"})

    assert response.json()["code"] == "reason_required"


def test_a_new_team_takes_a_category_and_a_technician_cannot_create_one(network, api_as):
    body = {
        "slug": "cloud",
        "name": "Cloud",
        "categories": ["software"],
        "move_categories": True,
        "reason": "Nhóm cloud mới",
    }

    refused = send(api_as(network.people["khoa"]), "post", "/api/teams", body)
    created = send(api_as(network.people["huy"]), "post", "/api/teams", body)

    assert refused.status_code == 403
    assert created.status_code == 201
    assert Team.objects.get(categories__category="software").slug == "cloud"


def test_a_keycloak_membership_is_not_edited_here(network, api_as):
    keycloak_user = person("quang.nv")
    keycloak_user.auth_source = AuthSource.OIDC.value
    keycloak_user.save(update_fields=["auth_source"])

    response = send(
        api_as(network.people["huy"]),
        "post",
        "/api/teams/network/members",
        {"username": "quang.nv", "role": "member"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "managed_by_keycloak"


def test_a_local_member_is_added_and_removed_with_audit(network, api_as):
    client = api_as(network.people["huy"])
    newcomer = person("tu.dv")

    added = send(client, "post", "/api/teams/network/members", {"username": "tu.dv"})
    removed = client.delete("/api/teams/network/members/tu.dv")

    assert (added.status_code, removed.status_code) == (200, 204)
    assert not TeamMembership.objects.filter(user=newcomer).exists()
    changes = [a.payload["change"] for a in AuditLog.objects.filter(event="membership_changed")]
    assert sorted(changes) == ["added", "removed"]
