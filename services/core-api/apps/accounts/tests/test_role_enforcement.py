"""Every route checks the caller's role in core-api (PRE-1)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from ninja import Router

from apps.accounts.models import User, UserRole
from apps.accounts.permissions import SessionAuth, gate_of
from apps.audit.models import AuditLog
from apps.itsm_mock.models import RunbookExecution
from apps.review.models import ReviewDecision, ReviewItem
from apps.tickets.models import AiRun, Ticket
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import ReviewQueue
from config.urls import api

# Sign-in, refresh, sign-out and the lifecycle callback (BR-PRE1-01).
UNGATED_BY_DESIGN = {
    "apps.accounts.views.login",
    "apps.accounts.views.refresh",
    "apps.accounts.views.logout",
    "apps.lifecycle.views.run_callback",
    "apps.accounts.views.oidc_config",
    "apps.accounts.views.oidc_exchange",
    "apps.accounts.views.oidc_backchannel_logout",
}


def ungated_routes(routers: Iterable[tuple[str, Router]]) -> list[str]:
    """Each route with no `require_role`, as "METHOD /path (module.handler)"."""
    found = []
    for prefix, router in routers:
        for path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                handler = operation.view_func
                name = f"{handler.__module__}.{handler.__name__}"
                if name in UNGATED_BY_DESIGN or gate_of(handler) is not None:
                    continue
                found.append(f"{','.join(operation.methods)} /api{prefix}{path} ({name})")
    return found


def user(username: str, role: UserRole) -> User:
    return User.objects.create_user(username=username, password="x", role=role.value)


def ticket(reporter: User, public_id: str, subject: str = "s") -> Ticket:
    return Ticket.objects.create(
        public_id=public_id,
        reporter=reporter,
        subject_masked=subject,
        body_masked="b",
        pii_level=PIILevel.ROUTINE.value,
    )


def runbook_item(reporter: User) -> ReviewItem:
    owner = ticket(reporter, "TKT-2026-000412")
    ai_run = AiRun.objects.create(
        ticket=owner,
        idempotency_key=f"{owner.id}:1",
        prompt_version="test",
        model="test",
        graph_version="test",
        trust_signals={},
        proposed_draft={
            "runbook_id": "RB-RESET-PASSWORD",
            "draft_payload": {"target_username": "lan.nt"},
        },
    )
    return ReviewItem.objects.create(
        ticket=owner, ai_run=ai_run, queue=ReviewQueue.RUNBOOK_APPROVAL.value
    )


APPROVE = {"action_taken": "approve", "time_spent_sec": 30}


def access_denied_rows(actor: User) -> int:
    return AuditLog.objects.filter(event="access_denied", actor_id=actor.id).count()


def test_every_route_is_gated():
    """FR-PRE1-004: every route but the four exempt ones declares its roles."""
    assert ungated_routes(api._routers) == []


def test_a_route_with_only_session_auth_is_named():
    """AC-PRE1-04: a route added with SessionAuth and no gate is reported by name."""
    router = Router()

    @router.get("/forgotten", auth=SessionAuth())
    def forgotten(request: Any) -> None: ...

    assert ungated_routes([("/scratch", router)]) == [
        f"GET /api/scratch/forgotten ({__name__}.forgotten)"
    ]


@pytest.mark.django_db
class TestTicketOwnership:
    def test_employee_cannot_read_another_ticket(self, api_as):
        """AC-PRE1-01: someone else's ticket is a 404 with no ticket data."""
        lan = user("lan.nt", UserRole.EMPLOYEE)
        ticket(user("duc.tm", UserRole.TECHNICIAN), "TKT-2026-000415", "VPN client báo lỗi")

        response = api_as(lan).get("/api/tickets/TKT-2026-000415")

        assert response.status_code == 404
        assert "VPN" not in response.content.decode()

    def test_employee_reads_own_ticket(self, api_as):
        """AC-PRE1-02: the reporter reads their own ticket."""
        lan = user("lan.nt", UserRole.EMPLOYEE)
        subject = "Không vào được AWS access portal, báo sai mật khẩu"
        ticket(lan, "TKT-2026-000412", subject)

        response = api_as(lan).get("/api/tickets/TKT-2026-000412")

        assert response.status_code == 200
        assert response.json()["subject_masked"] == subject

    @pytest.mark.parametrize("role", [UserRole.TECHNICIAN, UserRole.MANAGER, UserRole.SECURITY])
    def test_staff_read_any_ticket(self, api_as, role):
        ticket(user("lan.nt", UserRole.EMPLOYEE), "TKT-2026-000412")

        response = api_as(user("staff", role)).get("/api/tickets/TKT-2026-000412")

        assert response.status_code == 200


@pytest.mark.django_db
class TestRefusals:
    def test_employee_cannot_decide_review_item(self, api_as):
        """AC-PRE1-03: an employee can't approve a runbook, and the refusal is audited."""
        lan = user("lan.nt", UserRole.EMPLOYEE)
        item = runbook_item(lan)

        response = api_as(lan).post(
            f"/api/review/items/{item.id}/decide", APPROVE, content_type="application/json"
        )

        assert response.status_code == 403
        assert response.json()["code"] == "role_not_allowed"
        item.refresh_from_db()
        assert item.state == "pending"
        assert not ReviewDecision.objects.exists()
        assert access_denied_rows(lan) == 1

    def test_refusal_uses_the_error_shape(self, api_as):
        """BR-X-08: a refusal carries code, message and details."""
        lan = user("lan.nt", UserRole.EMPLOYEE)

        response = api_as(lan).get("/api/metrics/dashboard")

        assert response.json() == {
            "code": "role_not_allowed",
            "message": "requires role in [manager, technician]",
            "details": {"role": "employee"},
        }

    def test_refusal_audit_row_names_route_method_and_role(self, api_as):
        """FR-PRE1-003: the access_denied row has user, route, method and role."""
        lan = user("lan.nt", UserRole.EMPLOYEE)

        api_as(lan).get("/api/review/queue")

        row = AuditLog.objects.get(event="access_denied")
        assert row.actor_id == lan.id
        assert row.payload == {"route": "api/review/queue", "method": "GET", "role": "employee"}

    def test_refusals_are_audited_once_per_window(self, api_as, monkeypatch):
        """BR-PRE1-03: one row per user, route and method within the window."""
        lan = user("lan.nt", UserRole.EMPLOYEE)
        client = api_as(lan)

        client.get("/api/review/queue")
        client.get("/api/review/queue")
        client.get("/api/metrics/dashboard")
        assert access_denied_rows(lan) == 2

        later = timezone.now() + timedelta(seconds=61)
        monkeypatch.setattr(timezone, "now", lambda: later)
        client.get("/api/review/queue")
        assert access_denied_rows(lan) == 3


@pytest.mark.django_db
class TestRunbooks:
    def test_security_cannot_approve_a_runbook(self, api_as):
        """FR-PRE1-005: the decider of a runbook_approval item is a technician or manager."""
        anh = user("anh.lh", UserRole.SECURITY)
        item = runbook_item(user("lan.nt", UserRole.EMPLOYEE))

        response = api_as(anh).post(
            f"/api/review/items/{item.id}/decide", APPROVE, content_type="application/json"
        )

        assert response.status_code == 403
        assert not ReviewDecision.objects.exists()

    def test_runbook_needs_staff_approver_and_executor(self, api_as):
        """FR-PRE1-005: a technician approves, a technician executes."""
        duc = user("duc.tm", UserRole.TECHNICIAN)
        item = runbook_item(user("lan.nt", UserRole.EMPLOYEE))
        client = api_as(duc)

        decided = client.post(
            f"/api/review/items/{item.id}/decide", APPROVE, content_type="application/json"
        )
        executed = client.post(f"/api/itsm/review-items/{item.id}/execute")

        assert decided.status_code == 200
        assert executed.status_code == 200
        assert RunbookExecution.objects.get().executed_by == duc

    @pytest.mark.parametrize("role", [UserRole.EMPLOYEE, UserRole.SECURITY])
    def test_only_staff_execute(self, api_as, role):
        item = runbook_item(user("lan.nt", UserRole.EMPLOYEE))
        ReviewDecision.objects.create(
            review_item=item,
            reviewer=user("duc.tm", UserRole.TECHNICIAN),
            action_taken="approve",
            time_spent_sec=30,
        )

        response = api_as(user("caller", role)).post(f"/api/itsm/review-items/{item.id}/execute")

        assert response.status_code == 403
        assert not RunbookExecution.objects.exists()


_ID = uuid.uuid4()
_STAFF = {UserRole.TECHNICIAN, UserRole.MANAGER, UserRole.SECURITY}
_TECH_MGR = {UserRole.TECHNICIAN, UserRole.MANAGER}
_ARTICLE = {"slug": "x", "title": "t", "body": "b", "category": "access"}
_REASON = {"reason": "a reason"}

# §h of 06-PRE-prerequisites.md: method, path, body, roles allowed.
GATED_ROUTES: list[tuple[str, str, dict[str, Any] | None, set[UserRole]]] = [
    ("get", "/api/review/queue", None, _STAFF),
    ("get", f"/api/review/items/{_ID}", None, _STAFF),
    ("post", f"/api/review/items/{_ID}/claim", None, _STAFF),
    ("post", f"/api/review/items/{_ID}/decide", APPROVE, _STAFF),
    ("post", "/api/kb", _ARTICLE, {UserRole.MANAGER}),
    ("post", "/api/kb/x/reingest", None, {UserRole.MANAGER}),
    ("post", "/api/kb/x/auto-reply-allowed", {"allowed": True, **_REASON}, {UserRole.MANAGER}),
    ("post", "/api/kb/x/risk-tier", {"risk_tier": "low", **_REASON}, {UserRole.MANAGER}),
    ("get", "/api/metrics/dashboard", None, _TECH_MGR),
    ("get", "/api/itsm/runbooks", None, _TECH_MGR),
    ("post", f"/api/itsm/review-items/{_ID}/execute", None, _TECH_MGR),
    ("get", "/api/fewshot/category/access", None, _TECH_MGR),
]

REFUSALS = [
    pytest.param(method, path, body, role, id=f"{role.value}-{method}-{path}")
    for method, path, body, allowed in GATED_ROUTES
    for role in UserRole
    if role not in allowed
]


@pytest.mark.django_db
@pytest.mark.parametrize("method,path,body,role", REFUSALS)
def test_a_role_outside_the_route_table_is_refused(api_as, method, path, body, role):
    """FR-PRE1-001: each route in §h refuses the roles it doesn't list."""
    client = api_as(user("caller", role))
    send = getattr(client, method)

    response = send(path, body, content_type="application/json") if body else send(path)

    assert response.status_code == 403
    assert response.json()["code"] == "role_not_allowed"


@pytest.mark.django_db
def test_a_refused_caller_is_refused_before_the_body_is_read(api_as):
    """BR-PRE1-03: a malformed body doesn't turn a refusal into an unaudited 422."""
    lan = user("lan.nt", UserRole.EMPLOYEE)

    response = api_as(lan).post("/api/kb", {}, content_type="application/json")

    assert response.status_code == 403
    assert response.json()["code"] == "role_not_allowed"
    assert "detail" not in response.json()
    assert access_denied_rows(lan) == 1


@pytest.mark.django_db
def test_only_a_manager_may_force_a_move(api_as, technician_user):
    from apps.lifecycle.tests.conftest import make_ticket

    ticket = make_ticket(user("lan.nt", UserRole.EMPLOYEE))

    response = api_as(technician_user).post(
        f"/api/lifecycle/tickets/{ticket.public_id}/move",
        {"status_id": str(ticket.workflow_status_id), "force": True},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "role_not_allowed"
    assert access_denied_rows(technician_user) == 1


@pytest.mark.parametrize("role", ["", "contractor"])
def test_an_unknown_role_is_not_support_staff(role):
    assert User(username="x", role=role).is_support_staff is False
