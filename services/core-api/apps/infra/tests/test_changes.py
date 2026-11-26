"""The infra change routes: a change is sent once, on the route's target, within the caller's
reach, for an open ticket on a staff route; a lost answer is `outcome_unknown` (F17 §h.1,
BR-F17-08..11, AC-F17-06..08, F16 BR-F16-05)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from cloud_sim.cloud import ServerStatus, VolumeStatus
from django.test import Client
from django.utils import timezone

from apps.accounts.domain.catalog import Permission, ScopeKind
from apps.accounts.models import Assignment, Language, Role, RolePermission, User
from apps.agent.models import AgentAction, AgentActionKind, AgentActionState
from apps.agent.testing import as_agent
from apps.audit.models import AuditLog
from apps.categories.models import Category
from apps.infra.models import Customer, CustomerLookup
from apps.infra.services import changes as changes_module
from apps.infra.tests.conftest import LAN_SUBJECT, CloudSim
from apps.lifecycle.domain.vocabulary import PipelineStatus
from apps.lifecycle.tests.conftest import make_ticket
from apps.notifications.domain.vocabulary import NotificationEvent
from apps.notifications.models import Message
from apps.tickets.models import CommentVisibility, Ticket, TicketComment

pytestmark = pytest.mark.django_db

JSON = "application/json"
SAO_MAI = "8fed0033-eaa7-5729-9e9c-824134fb7ac2"
HOA_BINH = "52c86fa9-0f2c-52f7-882e-15b1696ab041"


@pytest.fixture(autouse=True)
def _no_pii(ner):
    """Every note's masking finds no PII."""


@pytest.fixture
def customer(employee_user: User) -> User:
    """lan.nt: a member of saomai-prod and saomai-staging in the cloud's Keystone."""
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    return employee_user


@pytest.fixture
def technician_user(technician_user: User) -> User:
    """The technician, reading in English."""
    technician_user.language = Language.EN.value
    technician_user.save(update_fields=["language"])
    return technician_user


@pytest.fixture
def ticket(employee_user: User) -> Ticket:
    """An open ticket past triage, raised by the employee."""
    return make_ticket(employee_user)


def post(
    client: Client,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    if body is None:
        return client.post(path, headers=headers)
    return client.post(path, body, content_type=JSON, headers=headers)


def apply(client: Client, path: str, action: AgentAction, body: dict[str, Any] | None = None):
    return post(client, path, body, {"X-Agent-Action": str(action.id)})


def proposed(response: Any) -> AgentAction:
    assert response.status_code == 202, response.content
    return AgentAction.objects.get(id=response.json()["action_id"])


def drafted(response: Any) -> AgentAction:
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "human_only_action"
    return AgentAction.objects.get(id=response.json()["details"]["draft_id"])


def notes(ticket: Ticket) -> list[TicketComment]:
    return list(
        TicketComment.objects.filter(ticket=ticket, visibility=CommentVisibility.INTERNAL.value)
    )


def owned_by(ticket: Ticket, domain_id: str, manager: User) -> Ticket:
    """`ticket`, stamped with the customer whose Keystone domain is `domain_id`."""
    customer = Customer.objects.create(
        name=domain_id, keystone_domain_id=domain_id, tier="standard", created_by=manager
    )
    Ticket.objects.filter(pk=ticket.pk).update(
        customer=customer, customer_lookup=CustomerLookup.FOUND.value
    )
    ticket.refresh_from_db()
    return ticket


def told() -> list[Message]:
    return list(Message.objects.filter(event=NotificationEvent.INFRA_CHANGE_ON_YOUR_RESOURCE.value))


# ── a lost answer ──


def test_a_confirmed_reboot_whose_answer_is_lost_is_sent_once_and_never_again(
    api_as, technician_user, manager_user, ticket, cloud_sim: CloudSim
):
    owned_by(ticket, SAO_MAI, manager_user)
    server = cloud_sim.id_of("servers", "db-01")
    path = f"/api/infra/servers/{server}/reboot"
    body = {"public_id": ticket.public_id}
    action = proposed(post(as_agent(technician_user, "reboot_server"), path, body))
    cloud_sim.lose_answers()

    first = apply(api_as(technician_user), path, action, body)
    again = apply(api_as(technician_user), path, action, body)

    assert first.status_code == 502
    assert first.json()["code"] == "infra_outcome_unknown"
    assert first.json()["details"] == {
        "change": "soft_reboot",
        "target_kind": "server",
        "target_id": server,
    }
    assert again.status_code == 409
    assert cloud_sim.changes() == [f"POST /compute/v2.1/servers/{server}/action"]
    action.refresh_from_db()
    assert action.state == AgentActionState.OUTCOME_UNKNOWN.value
    row = AuditLog.objects.get(event="infra_change")
    assert row.payload["outcome"] == "unknown"
    assert row.payload["via"] == "agent"
    assert AuditLog.objects.filter(event="agent_action_outcome_unknown").count() == 1
    assert not AuditLog.objects.filter(event="agent_action_applied").exists()
    (note,) = notes(ticket)
    assert "answer was lost" in note.body_masked
    assert told() == []


def test_a_persons_change_whose_answer_is_lost_answers_502_after_one_call(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    volume = cloud_sim.id_of("volumes", "vol-db-01")
    cloud_sim.lose_answers()

    response = post(
        api_as(technician_user),
        f"/api/infra/volumes/{volume}/detach",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 502
    assert response.json()["code"] == "infra_outcome_unknown"
    assert len(cloud_sim.changes()) == 1


def test_a_change_never_sent_is_unavailable_and_its_action_stays_pending(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    server = cloud_sim.id_of("servers", "db-01")
    path = f"/api/infra/servers/{server}/stop"
    body = {"public_id": ticket.public_id}
    action = proposed(post(as_agent(technician_user, "stop_server"), path, body))
    cloud_sim.refuse_changes()

    response = apply(api_as(technician_user), path, action, body)

    assert response.status_code == 424
    assert response.json()["code"] == "infra_backend_unavailable"
    assert cloud_sim.cloud.servers[server].status is ServerStatus.ACTIVE
    action.refresh_from_db()
    assert action.state == AgentActionState.PENDING.value
    assert not AuditLog.objects.filter(event="infra_change").exists()
    assert notes(ticket) == []


# ── the caller's reach ──


def test_a_customer_cannot_change_another_companys_server_404_like_a_missing_one(
    api_as, customer, cloud_sim: CloudSim
):
    other = cloud_sim.id_of("servers", "web-03")

    refused = post(api_as(customer), f"/api/requester/infra/servers/{other}/reboot", {})
    missing = post(api_as(customer), "/api/requester/infra/servers/no-such-server/reboot", {})

    assert refused.status_code == missing.status_code == 404
    assert refused.json() == missing.json()
    assert refused.json()["code"] == "infra_not_found"
    assert cloud_sim.changes() == []
    assert cloud_sim.cloud.servers[other].status is ServerStatus.ACTIVE


def test_a_customers_confirmed_stop_on_another_companys_server_sends_nothing(
    api_as, customer, cloud_sim: CloudSim
):
    other = cloud_sim.id_of("servers", "web-03")
    path = f"/api/requester/infra/servers/{other}/stop"
    action = proposed(post(as_agent(customer, "stop_my_server"), path))

    response = apply(api_as(customer), path, action)

    assert response.status_code == 404
    assert cloud_sim.changes() == []


def test_a_customer_stops_and_starts_their_own_server_with_no_ticket(
    api_as, customer, cloud_sim: CloudSim
):
    server = cloud_sim.id_of("servers", "app-02")

    stopped = post(api_as(customer), f"/api/requester/infra/servers/{server}/stop")

    assert stopped.status_code == 200, stopped.content
    assert stopped.json() == {
        "change": "stop",
        "target_kind": "server",
        "target_id": server,
        "target_name": "app-02",
        "project_id": cloud_sim.cloud.servers[server].project_id,
        "ticket": None,
    }
    cloud_sim.settle()
    started = post(api_as(customer), f"/api/requester/infra/servers/{server}/start")
    assert started.status_code == 200, started.content
    rows = AuditLog.objects.filter(event="infra_change").order_by("occurred_at")
    assert [(r.payload["change"], r.ticket_id) for r in rows] == [("stop", None), ("start", None)]
    assert not TicketComment.objects.exists()


def test_a_customer_cannot_hard_reboot(api_as, customer, cloud_sim: CloudSim):
    server = cloud_sim.id_of("servers", "app-02")

    response = post(
        api_as(customer), f"/api/requester/infra/servers/{server}/reboot", {"type": "hard"}
    )

    assert response.status_code == 422
    assert cloud_sim.changes() == []


# ── the target is the route's ──


def test_an_actions_target_is_the_routes_never_a_resource_its_body_names(
    technician_user, ticket, cloud_sim: CloudSim
):
    volume = cloud_sim.id_of("volumes", "vol-backup-01")
    server = cloud_sim.id_of("servers", "app-01")

    action = proposed(
        post(
            as_agent(technician_user, "attach_volume"),
            f"/api/infra/volumes/{volume}/attach",
            {"public_id": ticket.public_id, "server_id": server},
        )
    )

    assert (action.target_kind, action.target_ref) == ("volume", volume)


def test_a_drafts_target_is_the_routes(technician_user, ticket, cloud_sim: CloudSim):
    group = cloud_sim.id_of("security_groups", "db")

    draft = drafted(
        post(
            as_agent(technician_user, "draft_security_rule"),
            f"/api/infra/security-groups/{group}/rules",
            {"public_id": ticket.public_id, "direction": "ingress", "protocol": "tcp"},
        )
    )

    assert (draft.target_kind, draft.target_ref) == ("security_group", group)


def test_a_body_naming_another_server_is_refused(api_as, technician_user, ticket, cloud_sim):
    server = cloud_sim.id_of("servers", "db-01")
    other = cloud_sim.id_of("servers", "app-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/servers/{server}/reboot",
        {"public_id": ticket.public_id, "server_id": other},
    )

    assert response.status_code == 422
    assert cloud_sim.changes() == []


def test_a_confirmed_action_runs_only_on_its_own_target(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    server = cloud_sim.id_of("servers", "db-01")
    other = cloud_sim.id_of("servers", "app-01")
    body = {"public_id": ticket.public_id}
    action = proposed(
        post(
            as_agent(technician_user, "reboot_server"), f"/api/infra/servers/{server}/reboot", body
        )
    )

    response = apply(api_as(technician_user), f"/api/infra/servers/{other}/reboot", action, body)

    assert response.status_code == 409
    assert response.json()["code"] == "agent_action_mismatch"
    assert cloud_sim.changes() == []


def test_a_drafts_target_cannot_change_when_a_person_applies_it(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    volume = cloud_sim.id_of("volumes", "vol-db-01")
    other = cloud_sim.id_of("volumes", "vol-app-01")
    body = {"public_id": ticket.public_id}
    draft = drafted(
        post(
            as_agent(technician_user, "detach_volume"), f"/api/infra/volumes/{volume}/detach", body
        )
    )

    response = apply(api_as(technician_user), f"/api/infra/volumes/{other}/detach", draft, body)

    assert response.status_code == 409
    assert cloud_sim.changes() == []


# ── the agent's tiers ──


def test_an_agents_soft_reboot_waits_for_the_person_then_runs_once(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    server = cloud_sim.id_of("servers", "db-01")
    path = f"/api/infra/servers/{server}/reboot"
    body = {"public_id": ticket.public_id}

    action = proposed(post(as_agent(technician_user, "reboot_server"), path, body))

    assert action.kind == AgentActionKind.CONFIRM.value
    assert cloud_sim.changes() == []
    assert cloud_sim.cloud.servers[server].status is ServerStatus.ACTIVE

    response = apply(api_as(technician_user), path, action, body)

    assert response.status_code == 200, response.content
    assert response.json()["change"] == "soft_reboot"
    assert response.json()["ticket"] == ticket.public_id
    assert cloud_sim.changes() == [f"POST /compute/v2.1/servers/{server}/action"]
    assert cloud_sim.cloud.servers[server].status is ServerStatus.REBOOT
    row = AuditLog.objects.get(event="infra_change")
    assert row.actor_id == technician_user.id
    assert row.payload["via"] == "agent"
    assert row.payload["agent_action_id"] == str(action.id)
    action.refresh_from_db()
    assert action.state == AgentActionState.APPLIED.value


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("servers/{server}/hard-reboot", {}),
        ("volumes/{volume}/detach", {}),
        ("security-groups/{group}/rules", {"direction": "ingress"}),
    ],
)
def test_an_agent_only_drafts_a_hard_reboot_detach_or_rule(
    technician_user, ticket, cloud_sim: CloudSim, route, body
):
    path = "/api/infra/" + route.format(
        server=cloud_sim.id_of("servers", "db-01"),
        volume=cloud_sim.id_of("volumes", "vol-db-01"),
        group=cloud_sim.id_of("security_groups", "db"),
    )

    draft = drafted(
        post(
            as_agent(technician_user, "draft_change"), path, {"public_id": ticket.public_id, **body}
        )
    )

    assert draft.kind == AgentActionKind.DRAFT.value
    assert cloud_sim.changes() == []
    assert cloud_sim.cloud.volumes[cloud_sim.id_of("volumes", "vol-db-01")].status is (
        VolumeStatus.IN_USE
    )


def test_a_person_applies_a_detach_draft(api_as, technician_user, ticket, cloud_sim: CloudSim):
    volume = cloud_sim.id_of("volumes", "vol-db-01")
    path = f"/api/infra/volumes/{volume}/detach"
    body = {"public_id": ticket.public_id}
    draft = drafted(post(as_agent(technician_user, "detach_volume"), path, body))

    response = apply(api_as(technician_user), path, draft, body)

    assert response.status_code == 200, response.content
    assert cloud_sim.changes() == [
        f"DELETE /compute/v2.1/servers/{cloud_sim.id_of('servers', 'db-01')}"
        f"/os-volume_attachments/{volume}"
    ]
    assert cloud_sim.cloud.volumes[volume].status is VolumeStatus.DETACHING
    row = AuditLog.objects.get(event="infra_change")
    assert row.payload["agent_draft_id"] == str(draft.id)


def test_a_draft_whose_volume_changed_since_is_409_and_stays(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    volume = cloud_sim.id_of("volumes", "vol-db-01")
    path = f"/api/infra/volumes/{volume}/detach"
    body = {"public_id": ticket.public_id}
    draft = drafted(post(as_agent(technician_user, "detach_volume"), path, body))
    assert post(api_as(technician_user), path, body).status_code == 200

    response = apply(api_as(technician_user), path, draft, body)

    assert response.status_code == 409
    assert response.json()["code"] == "infra_state_changed"
    assert len(cloud_sim.changes()) == 2
    draft.refresh_from_db()
    assert draft.state == AgentActionState.PENDING.value


# ── the ticket a staff change is for ──


def security_operator(security_user: User) -> User:
    """Security staff who may also operate the cloud: they work security tickets only."""
    role = Role.objects.create(urn="urn:smart-ticket:role:custom:cloud-operator", name="Operator")
    RolePermission.objects.create(role=role, permission_urn=Permission.INFRA_OPERATE.value)
    Assignment.objects.create(
        user=security_user,
        role=role,
        scope_kind=ScopeKind.GLOBAL.value,
        starts_at=timezone.now() - timedelta(days=1),
    )
    return security_user


@pytest.mark.parametrize("case", ["missing", "resolved", "in_triage", "not_theirs"])
def test_a_staff_change_needs_an_open_ticket_the_person_works_on(
    api_as, technician_user, employee_user, security_user, cloud_sim: CloudSim, case
):
    actor = technician_user
    if case == "missing":
        public_id = "TKT-NONE"
    elif case == "resolved":
        done = make_ticket(employee_user)
        Ticket.objects.filter(pk=done.pk).update(resolved_at=timezone.now())
        public_id = done.public_id
    elif case == "in_triage":
        public_id = make_ticket(employee_user, at=PipelineStatus.NEW).public_id
    else:
        public_id = make_ticket(employee_user).public_id
        actor = security_operator(security_user)
    server = cloud_sim.id_of("servers", "db-01")

    response = post(api_as(actor), f"/api/infra/servers/{server}/reboot", {"public_id": public_id})

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "infra_ticket_required"
    assert cloud_sim.changes() == []


def test_security_staff_may_change_for_a_security_ticket(
    api_as, employee_user, security_user, cloud_sim: CloudSim
):
    covered = make_ticket(employee_user)
    Ticket.objects.filter(pk=covered.pk).update(
        category=Category.objects.get(is_security=True).slug
    )
    actor = security_operator(security_user)
    server = cloud_sim.id_of("servers", "db-01")

    response = post(
        api_as(actor), f"/api/infra/servers/{server}/reboot", {"public_id": covered.public_id}
    )

    assert response.status_code == 200, response.content


def test_a_staff_change_without_a_ticket_is_refused_by_its_schema(
    api_as, technician_user, cloud_sim: CloudSim
):
    server = cloud_sim.id_of("servers", "db-01")

    response = post(api_as(technician_user), f"/api/infra/servers/{server}/reboot", {})

    assert response.status_code == 422
    assert cloud_sim.changes() == []


# ── the cloud refuses ──


def test_starting_a_running_server_is_a_changed_state_409(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    server = cloud_sim.id_of("servers", "db-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/servers/{server}/start",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "infra_state_changed"
    assert not AuditLog.objects.filter(event="infra_change").exists()
    assert notes(ticket) == []


def test_detaching_a_volume_attached_nowhere_sends_nothing(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    volume = cloud_sim.id_of("volumes", "vol-backup-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/volumes/{volume}/detach",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "infra_state_changed"
    assert cloud_sim.changes() == []


def test_attaching_a_volume_to_another_projects_server_is_refused(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    volume = cloud_sim.id_of("volumes", "vol-backup-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/volumes/{volume}/attach",
        {"public_id": ticket.public_id, "server_id": cloud_sim.id_of("servers", "web-04")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "infra_change_refused"
    assert response.json()["message"] == "the volume and the server are in different projects"
    assert cloud_sim.changes() == []
    assert cloud_sim.cloud.volumes[volume].status is VolumeStatus.AVAILABLE


def test_a_missing_server_is_not_found(api_as, technician_user, ticket, cloud_sim: CloudSim):
    response = post(
        api_as(technician_user),
        "/api/infra/servers/no-such-server/stop",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "infra_not_found"
    assert cloud_sim.changes() == []


# ── a change made ──


def test_a_staff_change_notes_the_ticket_audits_and_tells_the_owning_requester(
    api_as, technician_user, employee_user, manager_user, ticket, cloud_sim: CloudSim
):
    owned_by(ticket, SAO_MAI, manager_user)
    volume = cloud_sim.id_of("volumes", "vol-backup-01")
    server = cloud_sim.id_of("servers", "app-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/volumes/{volume}/attach",
        {"public_id": ticket.public_id, "server_id": server},
    )

    assert response.status_code == 200, response.content
    assert response.json() == {
        "change": "attach_volume",
        "target_kind": "volume",
        "target_id": volume,
        "target_name": "vol-backup-01",
        "project_id": cloud_sim.cloud.volumes[volume].project_id,
        "ticket": ticket.public_id,
    }
    assert cloud_sim.cloud.volumes[volume].server_id == server
    (note,) = notes(ticket)
    assert note.author == technician_user
    assert "vol-backup-01" in note.body_masked and "app-01" in note.body_masked
    row = AuditLog.objects.get(event="infra_change")
    assert row.ticket_id == ticket.id
    assert row.payload["outcome"] == "done"
    assert row.payload["ticket_public_id"] == ticket.public_id
    assert {m.user for m in told()} == {employee_user}


@pytest.mark.parametrize("domain", [HOA_BINH, None])
def test_a_change_to_a_resource_the_tickets_company_does_not_own_tells_no_one(
    api_as, technician_user, manager_user, ticket, cloud_sim: CloudSim, domain
):
    if domain is not None:
        owned_by(ticket, domain, manager_user)
    server = cloud_sim.id_of("servers", "db-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/servers/{server}/reboot",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 200, response.content
    assert len(notes(ticket)) == 1
    assert told() == []


def test_a_project_lookup_that_fails_tells_no_one_and_keeps_the_change(
    api_as, technician_user, manager_user, ticket, cloud_sim: CloudSim
):
    owned_by(ticket, SAO_MAI, manager_user)
    server = cloud_sim.id_of("servers", "db-01")

    def refuse(request: httpx.Request) -> None:
        if "/identity/v3/projects/" in request.url.path:
            raise httpx.ConnectError("refused", request=request)

    cloud_sim.client.event_hooks["request"].insert(0, refuse)

    response = post(
        api_as(technician_user),
        f"/api/infra/servers/{server}/reboot",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 200, response.content
    assert cloud_sim.cloud.servers[server].status is ServerStatus.REBOOT
    assert told() == []


def test_a_change_made_whose_notice_fails_stays_applied_and_is_never_confirmed_again(
    api_as, technician_user, manager_user, ticket, cloud_sim: CloudSim, monkeypatch
):
    owned_by(ticket, SAO_MAI, manager_user)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the notice and its fallback failed")

    monkeypatch.setattr(changes_module.notifier, "emit", fail)
    server = cloud_sim.id_of("servers", "db-01")
    path = f"/api/infra/servers/{server}/reboot"
    body = {"public_id": ticket.public_id}
    action = proposed(post(as_agent(technician_user, "reboot_server"), path, body))

    first = apply(api_as(technician_user), path, action, body)
    again = apply(api_as(technician_user), path, action, body)

    assert first.status_code == 200, first.content
    assert again.status_code == 409
    assert cloud_sim.changes() == [f"POST /compute/v2.1/servers/{server}/action"]
    action.refresh_from_db()
    assert action.state == AgentActionState.APPLIED.value


def test_a_rule_is_added_and_removed_on_its_group(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    group = cloud_sim.id_of("security_groups", "db")
    path = f"/api/infra/security-groups/{group}/rules"
    client = api_as(technician_user)

    added = post(
        client,
        path,
        {
            "public_id": ticket.public_id,
            "direction": "ingress",
            "protocol": "tcp",
            "port_range_min": 22,
            "port_range_max": 22,
            "remote_ip_prefix": "10.10.0.0/24",
        },
    )

    assert added.status_code == 200, added.content
    rule = next(r for r in cloud_sim.cloud.security_groups[group].rules if r.port_min == 22)
    removed = client.delete(
        path, {"public_id": ticket.public_id, "rule_id": rule.id}, content_type=JSON
    )
    assert removed.status_code == 200, removed.content
    assert rule.id not in {r.id for r in cloud_sim.cloud.security_groups[group].rules}
    assert [n.body_masked.split(" ")[0] for n in notes(ticket)] == ["New", "Removal"]


def test_removing_another_groups_rule_is_not_found(
    api_as, technician_user, ticket, cloud_sim: CloudSim
):
    group = cloud_sim.id_of("security_groups", "db")
    web = cloud_sim.id_of("security_groups", "web")
    rule = cloud_sim.cloud.security_groups[web].rules[0]

    response = api_as(technician_user).delete(
        f"/api/infra/security-groups/{group}/rules",
        {"public_id": ticket.public_id, "rule_id": rule.id},
        content_type=JSON,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "infra_not_found"
    assert cloud_sim.changes() == []


def test_a_rule_with_ports_needs_tcp_or_udp(api_as, technician_user, ticket, cloud_sim):
    group = cloud_sim.id_of("security_groups", "db")

    response = post(
        api_as(technician_user),
        f"/api/infra/security-groups/{group}/rules",
        {"public_id": ticket.public_id, "direction": "ingress", "port_range_min": 22},
    )

    assert response.status_code == 422
    assert cloud_sim.changes() == []


def test_a_failed_note_never_hides_a_change_made(
    api_as, technician_user, ticket, cloud_sim: CloudSim, ner
):
    def fail(text: str) -> Any:
        raise RuntimeError("NER down")

    ner(fail)
    server = cloud_sim.id_of("servers", "db-01")

    response = post(
        api_as(technician_user),
        f"/api/infra/servers/{server}/reboot",
        {"public_id": ticket.public_id},
    )

    assert response.status_code == 200, response.content
    assert cloud_sim.cloud.servers[server].status is ServerStatus.REBOOT
    assert AuditLog.objects.filter(event="infra_change").count() == 1
