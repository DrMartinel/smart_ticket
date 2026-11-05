"""Roles, scoped grants, departments, people and access reviews (F14, ADR-0045)."""

from __future__ import annotations

import ast
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.accounts.models import (
    AccessReviewItem,
    Assignment,
    Department,
    NoAnswer,
    PersonStatus,
    RefreshSession,
    ReviewDecisionKind,
    Role,
    RolePermission,
    User,
)
from apps.accounts.testing import grant_capability
from apps.accounts.utils.access import Access
from apps.accounts.utils.catalog import (
    PERMISSIONS,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    ScopeKind,
    SystemRole,
)
from apps.accounts.utils.departments import DepartmentDraft, departments
from apps.accounts.utils.grants import GrantRequest, grants
from apps.accounts.utils.org_import import org_import
from apps.accounts.utils.people import Profile, people
from apps.accounts.utils.reviews import CampaignRequest, access_reviews
from apps.accounts.utils.roles import RoleDraft, roles
from apps.accounts.utils.vocabulary import OrgError, OrgRefusal
from apps.lifecycle.tests.conftest import make_ticket
from apps.teams.models import MembershipRole, Team, TeamMembership
from apps.teams.utils.config import team_config
from apps.tickets.models import Ticket

JSON = "application/json"
ROUTER = Path(__file__).resolve().parents[2] / "tickets" / "utils" / "router.py"


def person(username: str, role: str = "technician", **extra) -> User:
    extra.setdefault("department", Department.objects.get(is_default=True))
    return User.objects.create_user(username=username, password="x", role=role, **extra)


def refused(code: OrgRefusal):
    """Expects an OrgError with `code`."""

    class Check:
        def __enter__(self):
            self.ctx = pytest.raises(OrgError)
            self.info = self.ctx.__enter__()
            return self.info

        def __exit__(self, *exc):
            handled = self.ctx.__exit__(*exc)
            assert self.info.value.code is code, self.info.value.code
            return handled

    return Check()


def give(actor: User, username: str, urn: str, kind=ScopeKind.GLOBAL, ref=None, **extra):
    return grants.grant(
        actor, GrantRequest(username, urn, kind, ref, reason="cover for leave", **extra)
    )


@pytest.fixture
def boss(db) -> User:
    return person("huy.pq", "manager")


@pytest.fixture
def deputy(db) -> User:
    return person("thao.vt", "manager")


@pytest.fixture
def finance(boss) -> Department:
    fin = departments.create(boss, "FIN", DepartmentDraft(name="Finance"), "new unit")
    departments.create(boss, "FIN-AP", DepartmentDraft(name="Payables", parent="FIN"), "new unit")
    departments.create(boss, "ENG", DepartmentDraft(name="Engineering"), "new unit")
    return fin


# ── roles ──


def test_custom_role_cannot_hold_a_locked_permission(boss):
    with refused(OrgRefusal.PERMISSION_LOCKED):
        roles.create(
            boss,
            RoleDraft("Leaky", "", [Permission.PII_REVEAL.value], reason="try"),
        )
    assert not Role.objects.filter(name="Leaky").exists()


def test_every_locked_permission_is_refused_on_a_custom_role(boss):
    for permission, spec in PERMISSIONS.items():
        if not spec.locked:
            continue
        with refused(OrgRefusal.PERMISSION_LOCKED):
            roles.create(boss, RoleDraft("Leaky", "", [permission.value], reason="try"))


def test_a_role_cannot_gain_a_permission_its_editor_lacks(db):
    secu = person("anh.lh", "security")
    grant_capability(secu, "workflow_admin")
    with refused(OrgRefusal.CANNOT_GRANT_UNHELD):
        roles.create(secu, RoleDraft("Auditor", "", [Permission.KB_PAGES_CREATE.value], "x"))


def test_api_cannot_create_a_system_urn(boss, api_as):
    response = api_as(boss).post(
        "/api/access/roles",
        json.dumps(
            {
                "name": "system:technician",
                "permissions": [Permission.TICKETS_READ.value],
                "reason": "copy",
            }
        ),
        content_type=JSON,
    )

    assert response.status_code == 200
    assert response.json()["urn"] == "urn:smart-ticket:role:custom:system-technician"
    assert Role.objects.get(urn=SystemRole.TECHNICIAN.value).is_system


def test_role_urn_never_changes_or_gets_reused(boss):
    role = roles.create(
        boss, RoleDraft("Read-only auditor", "", [Permission.TICKETS_READ.value], "audit")
    )
    roles.update(boss, role.urn, RoleDraft("Auditors", None, None, "rename"))
    role.refresh_from_db()
    assert role.urn == "urn:smart-ticket:role:custom:read-only-auditor"
    assert role.name == "Auditors"

    roles.retire(boss, role.urn, "not needed")
    with refused(OrgRefusal.ROLE_URN_TAKEN):
        roles.create(boss, RoleDraft("Read-only auditor", "", [Permission.TICKETS_READ.value], "x"))


def test_a_system_role_cannot_be_edited_or_retired(boss):
    with refused(OrgRefusal.ROLE_IS_SYSTEM):
        roles.update(
            boss,
            SystemRole.TECHNICIAN.value,
            RoleDraft(None, None, [Permission.TICKETS_READ.value], "x"),
        )
    with refused(OrgRefusal.ROLE_IS_SYSTEM):
        roles.retire(boss, SystemRole.MANAGER.value, "x")


def test_a_new_permission_reaches_no_existing_role(boss):
    role = roles.create(boss, RoleDraft("Readers", "", [Permission.TICKETS_READ.value], "x"))
    tu = person("tu.dv")
    give(boss, "tu.dv", role.urn)

    assert set(Access.of(tu).sources) - SYSTEM_ROLE_PERMISSIONS[SystemRole.TECHNICIAN] == set()
    assert set(
        RolePermission.objects.filter(role=role).values_list("permission_urn", flat=True)
    ) == {Permission.TICKETS_READ.value}


def test_retiring_a_role_ends_its_grants(boss):
    role = roles.create(boss, RoleDraft("Readers", "", [Permission.KB_GRAPH_READ.value], "x"))
    tu = person("tu.dv")
    give(boss, "tu.dv", role.urn)
    assert Access.of(tu).holds(Permission.KB_GRAPH_READ)

    roles.retire(boss, role.urn, "gone")

    Access.forget(tu)
    assert not Access.of(tu).holds(Permission.KB_GRAPH_READ)
    assert Assignment.objects.get(role=role).ended_reason == "role_retired"


# ── grants ──


def test_cannot_grant_a_permission_you_lack(boss, deputy):
    role = roles.create(boss, RoleDraft("Desk", "", [Permission.TICKETS_READ.value], "x"))
    grant_capability(boss, "kb_editor")
    graph = roles.create(boss, RoleDraft("Graph", "", [Permission.KB_GRAPH_EDIT.value], "x"))
    person("tu.dv")

    give(deputy, "tu.dv", role.urn)
    with refused(OrgRefusal.CANNOT_GRANT_UNHELD):
        give(deputy, "tu.dv", graph.urn)


def test_only_an_access_admin_grants_a_system_role(db):
    lead = person("duc.tm")
    grant_capability(lead, "workflow_admin")
    person("tu.dv")
    with refused(OrgRefusal.CANNOT_GRANT_UNHELD):
        give(lead, "tu.dv", SystemRole.KB_EDITOR.value)


def test_nobody_changes_their_own_grants(boss):
    with refused(OrgRefusal.OWN_RIGHTS):
        give(boss, "huy.pq", SystemRole.KB_EDITOR.value)


def test_an_employee_gets_no_staff_role(boss):
    person("lan.nt", "employee")
    with refused(OrgRefusal.STAFF_ONLY):
        give(boss, "lan.nt", SystemRole.KB_EDITOR.value)


def test_a_structural_role_is_not_granted_by_hand(boss):
    person("tu.dv")
    with refused(OrgRefusal.ROLE_IS_STRUCTURAL):
        give(boss, "tu.dv", SystemRole.TEAM_LEAD.value, ScopeKind.TEAM, "network")
    with refused(OrgRefusal.ROLE_IS_BASE):
        give(boss, "tu.dv", SystemRole.MANAGER.value)


def test_a_role_is_granted_only_at_a_scope_it_allows(boss):
    person("tu.dv")
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        give(boss, "tu.dv", SystemRole.KB_EDITOR.value, ScopeKind.TEAM, "network")


def test_rights_change_ends_sessions(boss, api_as):
    tu = person("tu.dv")
    api_as(tu)
    assert RefreshSession.objects.filter(user=tu, revoked_at__isnull=True).exists()

    give(boss, "tu.dv", SystemRole.KB_EDITOR.value)

    assert not RefreshSession.objects.filter(user=tu, revoked_at__isnull=True).exists()


def test_expired_grant_admits_nobody(boss):
    tu = person("tu.dv")
    row = give(
        boss, "tu.dv", SystemRole.KB_EDITOR.value, ends_at=timezone.now() + timedelta(hours=1)
    )
    Assignment.objects.filter(pk=row.pk).update(ends_at=timezone.now() - timedelta(seconds=1))

    Access.forget(tu)
    assert not Access.of(tu).holds(Permission.KB_DRAFTS_MANAGE)

    result = grants.sweep()
    row.refresh_from_db()
    assert result["expired"] == 1
    assert row.ended_reason == "expired"


def test_a_grant_ending_soon_is_noticed_once(boss):
    person("tu.dv")
    give(boss, "tu.dv", SystemRole.KB_EDITOR.value, ends_at=timezone.now() + timedelta(hours=2))

    assert grants.sweep()["noticed"] == 1
    assert grants.sweep()["noticed"] == 0


def test_a_grant_cannot_end_before_it_starts(boss):
    person("tu.dv")
    with refused(OrgRefusal.ENDS_BEFORE_START):
        give(boss, "tu.dv", SystemRole.KB_EDITOR.value, ends_at=timezone.now() - timedelta(days=1))


def test_last_access_admin_cannot_be_removed(boss, glass_user):
    with refused(OrgRefusal.LAST_ACCESS_ADMIN):
        grants.check_not_last_admin(boss)
    with refused(OrgRefusal.LAST_ACCESS_ADMIN):
        people.deactivate(glass_user, "huy.pq", "leaving")
    assert User.objects.get(username="huy.pq").is_active


def test_a_structural_grant_ends_only_with_its_structure(boss):
    duc = person("duc.tm")
    network = Team.objects.get(slug="network")
    team_config.add_member(boss, network, duc, MembershipRole.LEAD)
    row = Assignment.objects.get(user=duc, role__urn=SystemRole.TEAM_LEAD.value)

    with refused(OrgRefusal.GRANT_IS_STRUCTURAL):
        grants.end(boss, row.id, "no")

    team_config.add_member(boss, network, duc, MembershipRole.MEMBER)
    row.refresh_from_db()
    assert row.ended_reason == "no_longer_lead"


def test_explain_matches_enforcement(boss):
    tu = person("tu.dv")
    give(boss, "tu.dv", SystemRole.KB_EDITOR.value)
    access = Access.of(tu)

    for permission in Permission:
        assert access.holds(permission) == bool(access.sources.get(permission)), permission
    assert {s.role_urn for s in access.sources[Permission.KB_DRAFTS_MANAGE]} == {
        SystemRole.KB_EDITOR.value
    }


def test_a_team_scoped_role_reaches_only_that_team(boss):
    from apps.reports.utils.reports import ReportError, Reports

    role = roles.create(
        boss, RoleDraft("Deputy lead", "", [Permission.REPORTS_TEAMS_READ.value], "cover")
    )
    vy = person("vy.nt", "technician")
    give(boss, "vy.nt", role.urn, ScopeKind.TEAM, "network")
    lan = person("lan.nt", "employee")
    network, access = make_ticket(lan), make_ticket(lan)
    Ticket.objects.filter(pk=network.pk).update(team=Team.objects.get(slug="network"))
    Ticket.objects.filter(pk=access.pk).update(team=Team.objects.get(slug="access"))

    assert Reports().team_scope(vy, None) == ["network"]
    with pytest.raises(ReportError):
        Reports().team_scope(vy, "access")
    scope = Access.of(vy)
    assert scope.covers_ticket(Permission.REPORTS_TEAMS_READ, Ticket.objects.get(pk=network.pk))
    assert not scope.covers_ticket(Permission.REPORTS_TEAMS_READ, Ticket.objects.get(pk=access.pk))


# ── departments ──


def test_department_scope_covers_descendants_only(boss, finance):
    lan = person("lan.nt", "employee")
    ap_clerk = person("mai.ap", "employee", department=Department.objects.get(code="FIN-AP"))
    engineer = person("khoa.eng", "employee", department=Department.objects.get(code="ENG"))
    departments.update(boss, "FIN", DepartmentDraft(head="lan.nt"), "new head")
    in_ap = make_ticket(ap_clerk)
    in_eng = make_ticket(engineer)

    visible = set(Ticket.objects.in_department_of(lan).values_list("pk", flat=True))

    assert in_ap.pk in visible
    assert in_eng.pk not in visible


def test_a_department_head_reads_their_subtree_over_the_api(boss, finance, api_as):
    lan = person("lan.nt", "employee")
    ap_clerk = person("mai.ap", "employee", department=Department.objects.get(code="FIN-AP"))
    engineer = person("khoa.eng", "employee", department=Department.objects.get(code="ENG"))
    departments.update(boss, "FIN", DepartmentDraft(head="lan.nt"), "new head")
    in_ap = make_ticket(ap_clerk)
    make_ticket(engineer)

    response = api_as(lan).get("/api/requester/department-tickets")

    assert response.status_code == 200
    assert [row["public_id"] for row in response.json()] == [in_ap.public_id]


def test_a_former_head_loses_the_department(boss, finance, api_as):
    lan = person("lan.nt", "employee")
    departments.update(boss, "FIN", DepartmentDraft(head="lan.nt"), "head")
    departments.update(boss, "FIN", DepartmentDraft(head=""), "no head")

    response = api_as(lan).get("/api/requester/department-tickets")

    assert response.status_code == 403
    assert response.json()["code"] == "permission_missing"


def test_a_department_cannot_move_under_itself(boss, finance):
    with refused(OrgRefusal.DEPARTMENT_CYCLE):
        departments.move(boss, "FIN", "FIN-AP", "loop")


def test_a_department_tree_has_a_depth_limit(boss, settings):
    limit = settings.THRESHOLDS.access.department_max_depth
    parent = None
    for level in range(limit):
        departments.create(boss, f"L{level}", DepartmentDraft(name=f"L{level}", parent=parent), "x")
        parent = f"L{level}"
    with refused(OrgRefusal.DEPARTMENT_TOO_DEEP):
        departments.create(boss, "DEEP", DepartmentDraft(name="Deep", parent=parent), "x")


def test_a_department_with_people_is_not_archived(boss, finance):
    person("mai.ap", "employee", department=Department.objects.get(code="FIN-AP"))
    with refused(OrgRefusal.DEPARTMENT_NOT_EMPTY):
        departments.archive(boss, "FIN-AP", "closing")
    with refused(OrgRefusal.DEPARTMENT_IS_DEFAULT):
        departments.archive(boss, Department.objects.get(is_default=True).code, "closing")


def test_a_movers_department_grants_are_flagged_then_end(boss, finance):
    role = roles.create(boss, RoleDraft("Desk", "", [Permission.TICKETS_READ.value], "x"))
    tu = person("tu.dv")
    give(boss, "tu.dv", role.urn, ScopeKind.DEPARTMENT, "FIN")

    people.update(boss, "tu.dv", Profile(department="ENG"), "moved")

    row = Assignment.objects.get(user=tu, role=role)
    assert row.needs_review and row.review_due_at is not None
    assert row.ended_at is None
    grants.sweep(row.review_due_at + timedelta(seconds=1))
    row.refresh_from_db()
    assert row.ended_reason == "mover_unconfirmed"


def test_a_confirmed_mover_grant_stays(boss, finance):
    role = roles.create(boss, RoleDraft("Desk", "", [Permission.TICKETS_READ.value], "x"))
    person("tu.dv")
    row = give(boss, "tu.dv", role.urn, ScopeKind.DEPARTMENT, "FIN")
    people.update(boss, "tu.dv", Profile(department="ENG"), "moved")

    grants.confirm(boss, row.id, "still covers finance")
    grants.sweep(timezone.now() + timedelta(days=365))

    row.refresh_from_db()
    assert row.ended_at is None and not row.needs_review


def test_a_line_manager_loop_is_refused(boss):
    person("a.one", line_manager=None)
    people.update(boss, "a.one", Profile(line_manager="huy.pq"), "x")
    with refused(OrgRefusal.LINE_MANAGER_INVALID):
        people.update(boss, "huy.pq", Profile(line_manager="a.one"), "x")


# ── people ──


def test_leaver_loses_grants_teams_and_tickets(boss):
    mai = person("mai.bn")
    network = Team.objects.get(slug="network")
    team_config.add_member(boss, network, mai, MembershipRole.LEAD)
    give(boss, "mai.bn", SystemRole.KB_EDITOR.value)
    lan = person("lan.nt", "employee")
    held = [make_ticket(lan) for _ in range(3)]
    Ticket.objects.filter(pk__in=[t.pk for t in held]).update(assigned_to=mai, team=network)

    people.deactivate(boss, "mai.bn", "left the company")

    mai.refresh_from_db()
    assert mai.status == PersonStatus.DEACTIVATED.value and not mai.is_active
    assert not TeamMembership.objects.filter(user=mai).exists()
    assert not Assignment.objects.active().filter(user=mai).exists()
    assert Assignment.objects.filter(user=mai).count() == 2
    assert not Ticket.objects.filter(assigned_to=mai).exists()
    assert set(
        Ticket.objects.filter(pk__in=[t.pk for t in held]).values_list("team__slug", flat=True)
    ) == {"network"}


def test_a_suspended_person_keeps_grants_but_cannot_sign_in(boss, api_as):
    tu = person("tu.dv")
    give(boss, "tu.dv", SystemRole.KB_EDITOR.value)
    client = api_as(tu)

    people.suspend(boss, "tu.dv", "investigation")

    assert client.get("/api/accounts/me").status_code == 401
    assert Assignment.objects.active().filter(user=tu).exists()
    people.reactivate(boss, "tu.dv", "cleared")
    tu.refresh_from_db()
    assert tu.is_active and tu.status == PersonStatus.ACTIVE.value


def test_a_break_glass_account_is_not_suspended(boss, glass_user):
    with refused(OrgRefusal.BREAK_GLASS_FIXED):
        people.suspend(boss, glass_user.username, "x")


def test_a_provisioned_person_links_and_activates_on_first_sign_in(boss):
    from apps.accounts.utils.oidc import Identities

    people.provision(
        boss, "new.hire", "New.Hire@example.com", Profile(job_title="Analyst"), "joiner"
    )
    invited = User.objects.get(username="new.hire")
    assert invited.status == PersonStatus.INVITED.value
    assert invited.department.is_default

    user = Identities().find_or_provision(
        {"sub": "kc-123", "email": "new.hire@example.com", "email_verified": True}
    )

    assert user.pk == invited.pk
    user.refresh_from_db()
    assert user.status == PersonStatus.ACTIVE.value and user.external_id == "kc-123"


def test_an_unverified_email_does_not_link_an_invite(boss):
    from apps.accounts.utils.oidc import Identities

    people.provision(boss, "new.hire", "new.hire@example.com", Profile(), "joiner")
    user = Identities().find_or_provision(
        {
            "sub": "kc-999",
            "email": "new.hire@example.com",
            "email_verified": False,
            "preferred_username": "new.hire",
        }
    )

    assert user.username != "new.hire"
    assert User.objects.get(username="new.hire").status == PersonStatus.INVITED.value


def test_provisioning_refuses_a_taken_email(boss):
    people.provision(boss, "a.one", "a@example.com", Profile(), "joiner")
    with refused(OrgRefusal.EMAIL_TAKEN):
        people.provision(boss, "a.two", "A@example.com", Profile(), "joiner")


# ── imports ──


def test_an_import_dry_run_changes_nothing(boss):
    text = "code,name,parent_code\nSALES-EU,Sales Europe,SALES\nSALES,Sales,\n"

    result = org_import.departments(boss, text, "reorg", dry_run=True)

    assert not result.applied
    assert [r.action for r in result.rows] == ["create", "create"]
    assert not Department.objects.filter(code__startswith="SALES").exists()


def test_an_import_with_a_bad_row_applies_nothing(boss):
    text = "code,name,parent_code\nSALES,Sales,\nBAD CODE,Broken,\n"

    result = org_import.departments(boss, text, "reorg", dry_run=False)

    assert not result.applied
    assert result.rows[1].errors and result.rows[1].errors[0].startswith("department_code_invalid")
    assert not Department.objects.filter(code="SALES").exists()


def test_a_people_import_applies_when_every_row_passes(boss, finance):
    text = "username,email,department_code,job_title\nnew.a,a@example.com,FIN,Clerk\nhuy.pq,,ENG,\n"

    result = org_import.people(boss, text, "hr feed", dry_run=False)

    assert result.applied
    assert User.objects.get(username="new.a").department.code == "FIN"
    assert User.objects.get(username="huy.pq").department.code == "ENG"


# ── reviews ──


def test_access_review_revokes_unanswered_grants(boss, deputy):
    tu = person("tu.dv")
    give(boss, "tu.dv", SystemRole.KB_EDITOR.value)
    campaign = access_reviews.open(
        boss,
        CampaignRequest(
            "Q4 editors", "thao.vt", NoAnswer.REVOKE, role_urn=SystemRole.KB_EDITOR.value
        ),
    )

    access_reviews.close(boss, campaign.id)

    row = Assignment.objects.get(user=tu, role__urn=SystemRole.KB_EDITOR.value)
    assert row.ended_reason == "review_no_answer"


def test_nobody_reviews_their_own_grant(boss, deputy):
    give(boss, "thao.vt", SystemRole.KB_EDITOR.value)
    campaign = access_reviews.open(
        boss, CampaignRequest("Q4", "thao.vt", NoAnswer.FLAG, role_urn=SystemRole.KB_EDITOR.value)
    )

    item = AccessReviewItem.objects.get(campaign=campaign)
    assert item.reviewer.username != "thao.vt"
    with refused(OrgRefusal.NOT_YOUR_REVIEW):
        access_reviews.decide(deputy, item.id, ReviewDecisionKind.KEEP, "")


def test_nobody_makes_themselves_a_department_head(boss, finance):
    with refused(OrgRefusal.OWN_RIGHTS):
        departments.set_head(boss, finance, "huy.pq")


def test_an_opener_reviewing_their_own_grant_passes_it_to_another_admin(boss, deputy):
    give(deputy, "huy.pq", SystemRole.KB_EDITOR.value)
    campaign = access_reviews.open(
        boss, CampaignRequest("Q4", "huy.pq", NoAnswer.FLAG, role_urn=SystemRole.KB_EDITOR.value)
    )

    item = AccessReviewItem.objects.get(campaign=campaign)
    assert item.reviewer == deputy


def test_a_review_only_its_grantee_could_answer_is_refused(boss, deputy):
    give(deputy, "huy.pq", SystemRole.KB_EDITOR.value)
    User.objects.filter(pk=deputy.pk).update(is_active=False)
    with refused(OrgRefusal.NO_OTHER_REVIEWER):
        access_reviews.open(
            boss,
            CampaignRequest("Q4", "huy.pq", NoAnswer.FLAG, role_urn=SystemRole.KB_EDITOR.value),
        )


def test_the_line_manager_reviews_and_a_keep_survives_close(boss, deputy):
    tu = person("tu.dv", line_manager=deputy)
    give(boss, "tu.dv", SystemRole.KB_EDITOR.value)
    campaign = access_reviews.open(
        boss, CampaignRequest("Q4", "huy.pq", NoAnswer.REVOKE, role_urn=SystemRole.KB_EDITOR.value)
    )
    item = AccessReviewItem.objects.get(campaign=campaign)
    assert item.reviewer == deputy

    access_reviews.decide(deputy, item.id, ReviewDecisionKind.KEEP, "still edits")
    access_reviews.close(boss, campaign.id)

    assert (
        Assignment.objects.active().filter(user=tu, role__urn=SystemRole.KB_EDITOR.value).exists()
    )


def test_an_empty_review_is_refused(boss):
    with refused(OrgRefusal.REVIEW_EMPTY):
        access_reviews.open(
            boss,
            CampaignRequest("Q4", "huy.pq", NoAnswer.FLAG, role_urn=SystemRole.KB_EDITOR.value),
        )


def test_a_custom_role_reaches_the_service_its_route_admits(boss, deputy):
    from apps.incidents.utils.incidents import incidents

    give(deputy, "huy.pq", SystemRole.INCIDENT_MANAGER.value)
    role = roles.create(
        boss, RoleDraft("Incident deputy", "", [Permission.INCIDENTS_MANAGE.value], "cover")
    )
    person("vy.nt", "technician")
    give(boss, "vy.nt", role.urn)

    incidents.check_manager(User.objects.get(username="vy.nt"))


def test_a_team_scoped_supervisor_sees_only_that_teams_queue(boss):
    from apps.teams.utils.people import TeamError
    from apps.teams.utils.people import people as team_people

    role = roles.create(
        boss, RoleDraft("Night supervisor", "", [Permission.TEAMS_SUPERVISE.value], "nights")
    )
    person("vy.nt", "technician")
    give(boss, "vy.nt", role.urn, ScopeKind.TEAM, "network")
    vy = User.objects.get(username="vy.nt")

    team_people.check_member_or_manager(vy, Team.objects.get(slug="network"))
    with pytest.raises(TeamError):
        team_people.check_member_or_manager(vy, Team.objects.get(slug="access"))


SERVICES = Path(__file__).resolve().parents[2]
ROLE_NAME_CHECK = re.compile(
    r"\.role\s*(==|!=)\s*UserRole\.|\.role not in \(UserRole|Capability\.\w+\.value in"
    r"|\.is_manager\b|\.is_security\b|may_run_runbooks"
)
BASE_ROLE_FILES = {
    "accounts/utils/rights.py",
    "accounts/utils/grants.py",
    "accounts/utils/access.py",
    "accounts/management/commands/set_break_glass.py",
}


def test_services_check_permissions_not_role_names():
    found = [
        f"{path.relative_to(SERVICES)}:{n}"
        for path in SERVICES.glob("*/**/*.py")
        if "tests" not in path.parts
        and "migrations" not in path.parts
        and str(path.relative_to(SERVICES)) not in BASE_ROLE_FILES
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if ROLE_NAME_CHECK.search(line)
    ]
    assert found == []


def test_an_employee_head_gets_no_staff_only_permission(boss, finance):
    person("lan.nt", "employee")
    departments.set_head(boss, finance, "lan.nt")

    held = Access.of(User.objects.get(username="lan.nt"))

    assert held.holds(Permission.REQUESTER_DEPARTMENT_READ)
    assert not held.holds(Permission.ORG_DEPARTMENTS_MANAGE)
    assert not held.holds(Permission.REPORTS_OPERATIONS_READ)


def test_a_head_renames_and_adds_below_but_not_above(boss, finance):
    person("tu.dv")
    departments.set_head(boss, finance, "tu.dv")
    tu = User.objects.get(username="tu.dv")

    departments.update(tu, "FIN-AP", DepartmentDraft(name="Payables team"), "clearer")
    departments.create(tu, "FIN-AR", DepartmentDraft(name="Receivables", parent="FIN"), "new")
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        departments.update(tu, "ENG", DepartmentDraft(name="Eng"), "try")
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        departments.create(tu, "TOP", DepartmentDraft(name="Top"), "try")
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        departments.update(tu, "FIN-AP", DepartmentDraft(head="lan.nt"), "try")
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        departments.archive(tu, "FIN-AR", "try")


def test_a_head_moves_people_only_within_their_subtree(boss, finance):
    person("tu.dv")
    departments.set_head(boss, finance, "tu.dv")
    tu = User.objects.get(username="tu.dv")
    lan = person("lan.nt", "employee", department=finance)
    person("an.lv", "employee")

    departments.move_person(tu, "FIN-AP", "lan.nt", "joins payables")
    lan.refresh_from_db()
    assert lan.department is not None and lan.department.code == "FIN-AP"
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        departments.move_person(tu, "FIN", "an.lv", "poach")
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        departments.move_person(tu, "ENG", "lan.nt", "push out")
    with refused(OrgRefusal.OWN_RIGHTS):
        departments.move_person(tu, "FIN-AP", "tu.dv", "self")


def test_a_heads_reports_cover_their_subtree_only(boss, finance):
    from apps.reports.utils.facts import ReportFacts
    from apps.reports.utils.reports import ReportError, Reports

    person("tu.dv", "security")
    departments.set_head(boss, finance, "tu.dv")
    tu = User.objects.get(username="tu.dv")
    payables = Department.objects.get(code="FIN-AP")
    make_ticket(person("lan.nt", "employee", department=payables))
    make_ticket(person("an.lv", "employee", department=Department.objects.get(code="ENG")))
    ReportFacts().build(full=True)

    _, rows = Reports().filtered(tu, None, None, None)

    assert set(rows.values_list("department", flat=True)) == {"FIN-AP"}
    assert Reports().department_scope(boss, "FIN") == ["FIN", "FIN-AP"]
    with pytest.raises(ReportError):
        Reports().department_scope(tu, "ENG")


def delegable_reporter(boss) -> str:
    return roles.create(
        boss,
        RoleDraft("Deputy reporter", "", [Permission.REPORTS_OPERATIONS_READ.value], "cover", True),
    ).urn


def test_a_head_grants_a_delegable_role_within_their_subtree(boss, finance):
    urn = delegable_reporter(boss)
    person("tu.dv", "security")
    departments.set_head(boss, finance, "tu.dv")
    tu = User.objects.get(username="tu.dv")
    person("vy.nt", "security", department=Department.objects.get(code="FIN-AP"))

    row = grants.grant(
        tu, GrantRequest("vy.nt", urn, ScopeKind.DEPARTMENT, "FIN-AP", "cover"), delegated=True
    )

    assert Access.of(User.objects.get(username="vy.nt")).holds(Permission.REPORTS_OPERATIONS_READ)
    grants.end(tu, row.id, "back", delegated=True)


def test_a_head_cannot_grant_a_role_not_marked_delegable(boss, finance):
    role = roles.create(
        boss, RoleDraft("Reporter", "", [Permission.REPORTS_OPERATIONS_READ.value], "x")
    )
    person("tu.dv", "security")
    departments.set_head(boss, finance, "tu.dv")
    person("vy.nt", "security", department=finance)

    with refused(OrgRefusal.ROLE_NOT_DELEGABLE):
        grants.grant(
            User.objects.get(username="tu.dv"),
            GrantRequest("vy.nt", role.urn, ScopeKind.DEPARTMENT, "FIN", "x"),
            delegated=True,
        )


def test_a_head_cannot_delegate_outside_their_subtree(boss, finance):
    urn = delegable_reporter(boss)
    person("tu.dv", "security")
    departments.set_head(boss, finance, "tu.dv")
    tu = User.objects.get(username="tu.dv")
    person("vy.nt", "security", department=Department.objects.get(code="ENG"))
    person("an.lv", "security", department=finance)

    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        grants.grant(
            tu, GrantRequest("vy.nt", urn, ScopeKind.DEPARTMENT, "FIN", "x"), delegated=True
        )
    with refused(OrgRefusal.SCOPE_NOT_ALLOWED):
        grants.grant(
            tu, GrantRequest("an.lv", urn, ScopeKind.DEPARTMENT, "ENG", "x"), delegated=True
        )


def test_a_head_is_offered_only_live_delegable_roles(boss, finance, api_as):
    urn = delegable_reporter(boss)
    roles.create(boss, RoleDraft("Reporter", "", [Permission.REPORTS_OPERATIONS_READ.value], "x"))
    tu = person("tu.dv", "security")
    departments.set_head(boss, finance, "tu.dv")

    response = api_as(tu).get("/api/org/delegable-roles")

    assert [r["urn"] for r in response.json()] == [urn]


def test_the_delegated_grant_route_refuses_an_employee_head(boss, finance, api_as):
    urn = delegable_reporter(boss)
    lan = person("lan.nt", "employee", department=finance)
    departments.set_head(boss, finance, "lan.nt")

    response = api_as(lan).post(
        "/api/org/departments/FIN/grants",
        json.dumps({"username": "lan.nt", "role": urn, "reason": "x"}),
        content_type="application/json",
    )

    assert response.status_code == 403


# ── boundaries ──


def test_router_imports_nothing_from_accounts():
    tree = ast.parse(ROUTER.read_text())
    imported = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not [m for m in imported if m.startswith("apps.accounts")]


def test_the_access_api_refuses_a_technician(api_as, technician_user):
    response = api_as(technician_user).get("/api/access/roles")

    assert response.status_code == 403
    assert response.json()["details"]["permission"] == Permission.ACCESS_READ.value


def test_the_access_api_explains_a_grant(boss, api_as):
    person("mai.bn")
    give(boss, "mai.bn", SystemRole.KB_EDITOR.value)

    response = api_as(boss).get(
        "/api/access/people/mai.bn/explain",
        {"permission": Permission.KB_DRAFTS_MANAGE.value},
    )

    body = response.json()
    assert response.status_code == 200 and body["holds"]
    assert body["sources"][0]["role_urn"] == SystemRole.KB_EDITOR.value
    assert body["sources"][0]["granted_by"] == "huy.pq"


def test_a_refused_grant_answers_with_its_code(boss, api_as):
    person("lan.nt", "employee")

    response = api_as(boss).post(
        "/api/access/people/lan.nt/assignments",
        json.dumps({"role": SystemRole.KB_EDITOR.value, "reason": "help"}),
        content_type=JSON,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "staff_only"
