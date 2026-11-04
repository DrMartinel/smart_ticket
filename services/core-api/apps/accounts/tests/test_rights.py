"""A manager sets people's roles and capabilities in the console (ADR-0042)."""

from __future__ import annotations

import json

import pytest

from apps.accounts.models import RefreshSession, User, UserCapability
from apps.audit.models import AuditLog
from apps.teams.models import Team, TeamMembership
from apps.tickets.models import Ticket

JSON = "application/json"


def person(username: str, role: str = "technician", **extra) -> User:
    return User.objects.create_user(username=username, password="x", role=role, **extra)


def put_rights(client, username: str, role: str, capabilities=(), reason: str = "new duties"):
    body = {"role": role, "capabilities": list(capabilities), "reason": reason}
    return client.put(
        f"/api/accounts/people/{username}/rights", json.dumps(body), content_type=JSON
    )


@pytest.fixture
def boss(db) -> User:
    return person("huy.pq", "manager")


def test_a_manager_sets_role_and_capabilities_and_ends_their_sign_ins(boss, api_as):
    tu = person("tu.dv")
    api_as(tu)

    response = put_rights(api_as(boss), "tu.dv", "manager", ["workflow_admin"])

    tu.refresh_from_db()
    assert response.status_code == 200
    assert (tu.role, tu.capability_set()) == ("manager", frozenset({"workflow_admin"}))
    assert not RefreshSession.objects.filter(user=tu, revoked_at__isnull=True).exists()
    (row,) = AuditLog.objects.filter(event="rights_changed")
    assert row.payload["before"] == {"role": "technician", "capabilities": []}


def test_nobody_changes_their_own_rights(boss, api_as):
    person("quang.nv", "manager")

    response = put_rights(api_as(boss), "huy.pq", "technician")

    assert response.status_code == 403
    assert response.json()["code"] == "own_rights"


def test_an_employee_holds_no_capabilities(boss, api_as):
    person("lan.nt", "employee")

    response = put_rights(api_as(boss), "lan.nt", "employee", ["kb_editor"])

    assert response.status_code == 422
    assert response.json()["code"] == "capability_needs_staff"


def test_an_employee_with_open_tickets_is_refused(boss, api_as):
    khoa = person("khoa.lv")
    Ticket.objects.create(
        public_id="TKT-RIGHTS-000001",
        reporter=person("lan.nt", "employee"),
        subject_masked="x",
        body_masked="x",
        pii_level="routine",
        assigned_to=khoa,
    )

    response = put_rights(api_as(boss), "khoa.lv", "employee")

    assert response.status_code == 409
    assert response.json()["code"] == "has_open_tickets"


def test_an_employee_leaves_every_team_and_capability(boss, api_as):
    khoa = person("khoa.lv")
    UserCapability.objects.create(user=khoa, capability="kb_editor")
    TeamMembership.objects.create(team=Team.objects.get(slug="network"), user=khoa)

    response = put_rights(api_as(boss), "khoa.lv", "employee")

    assert response.status_code == 200
    assert not TeamMembership.objects.filter(user=khoa).exists()
    assert khoa.capability_set() == frozenset()
    assert AuditLog.objects.get(event="rights_changed").payload["left_teams"] == ["network"]


def test_a_break_glass_account_stays_a_manager(boss, api_as):
    person("glass", "manager", is_break_glass=True)

    response = put_rights(api_as(boss), "glass", "technician")

    assert response.status_code == 409
    assert response.json()["code"] == "break_glass_fixed"


def test_a_change_needs_a_reason(boss, api_as):
    person("tu.dv")

    response = put_rights(api_as(boss), "tu.dv", "security", reason=" ")

    assert response.status_code == 422
    assert response.json()["code"] == "reason_required"


def test_a_workflow_admin_lists_people_but_sets_no_rights(boss, api_as):
    tu = person("tu.dv")
    UserCapability.objects.create(user=tu, capability="workflow_admin")
    person("lan.nt", "employee")

    listed = api_as(tu).get("/api/accounts/people")
    refused = put_rights(api_as(tu), "lan.nt", "technician")

    assert listed.status_code == 200
    assert {"huy.pq", "lan.nt", "tu.dv"} <= {p["username"] for p in listed.json()}
    assert refused.status_code == 403
