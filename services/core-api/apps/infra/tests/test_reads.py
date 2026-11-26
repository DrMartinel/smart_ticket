"""The infra read routes: scope, refusals, masking and the `infra_queries` row each read writes
(F17 §h.1, BR-F17-02..06, BR-F17-10, AC-F17-01, AC-F17-05)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from cloud_sim.faults import FaultKind

from apps.accounts.models import User
from apps.agent.testing import as_agent
from apps.infra.models import InfraQuery
from apps.infra.tests.conftest import (
    LAN_SUBJECT,
    CloudSim,
    FakeAlertmanager,
    FakeCloud,
    alert,
    mock_http,
)
from apps.infra.utils import inventory
from apps.infra.utils.clients import OpenStack
from apps.infra.utils.untrusted import WITHHELD
from apps.tickets.utils.masking import NERError

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer(employee_user: User) -> User:
    """lan.nt: a member of saomai-prod and saomai-staging in the cloud's Keystone."""
    employee_user.external_id = LAN_SUBJECT
    employee_user.save(update_fields=["external_id"])
    return employee_user


def names(reply: Any) -> set[str]:
    return {row["name"] for row in reply.json()}


# ── scope ──


def test_a_customer_cannot_see_another_companys_server_404_like_a_missing_one(
    api_as, customer, cloud_sim: CloudSim
):
    other = api_as(customer).get(
        f"/api/requester/infra/servers/{cloud_sim.id_of('servers', 'web-03')}"
    )
    missing = api_as(customer).get("/api/requester/infra/servers/no-such-server")

    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    assert other.json()["code"] == "infra_not_found"


def test_a_customer_cannot_see_another_companys_volume_or_network(
    api_as, customer, cloud_sim: CloudSim
):
    volume = api_as(customer).get(
        f"/api/requester/infra/volumes/{cloud_sim.id_of('volumes', 'vol-web-03')}"
    )
    network = api_as(customer).get(
        f"/api/requester/infra/networks/{cloud_sim.id_of('networks', 'hbr-web-net')}"
    )

    assert volume.status_code == network.status_code == 404


def test_a_customer_lists_only_their_companys_resources(api_as, customer, cloud_sim: CloudSim):
    client = api_as(customer)

    assert names(client.get("/api/requester/infra/projects")) == {"saomai-prod", "saomai-staging"}
    assert names(client.get("/api/requester/infra/servers")) == {
        "db-01",
        "app-01",
        "app-02",
        "stg-app-01",
    }
    assert "vol-web-03" not in names(client.get("/api/requester/infra/volumes"))
    assert names(client.get("/api/requester/infra/networks")) == {
        "saomai-prod-net",
        "saomai-staging-net",
    }


def test_a_customer_asking_for_another_companys_project_gets_nothing(
    api_as, customer, cloud_sim: CloudSim
):
    hbr = cloud_sim.id_of("projects", "hbr-web")

    reply = api_as(customer).get("/api/requester/infra/servers", {"project_id": hbr})

    assert reply.json() == []
    assert not [c for c in cloud_sim.calls if "servers" in c]


def test_a_failed_membership_lookup_refuses_and_never_widens(api_as, customer, cloud_sim: CloudSim):
    cloud_sim.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    reply = api_as(customer).get("/api/requester/infra/servers")

    assert reply.status_code == 424
    assert reply.json()["code"] == "infra_scope_unavailable"
    row = InfraQuery.objects.get()
    assert (row.outcome, row.refusal) == ("scope_unavailable", "infra_scope_unavailable")


def test_a_customer_listed_twice_in_keystone_is_refused(api_as, customer, cloud_sim: CloudSim):
    lan = next(u for u in cloud_sim.cloud.users.values() if u.subject == LAN_SUBJECT)
    twin = type(lan)(**{**lan.__dict__, "id": "twin", "name": "lan.nt-2"})
    cloud_sim.cloud.users["twin"] = twin

    reply = api_as(customer).get("/api/requester/infra/servers")

    assert reply.json()["code"] == "infra_scope_unavailable"


def test_a_person_without_a_keystone_user_sees_nothing(api_as, employee_user, cloud_sim: CloudSim):
    unlinked = api_as(employee_user).get("/api/requester/infra/servers")
    employee_user.external_id = "8f0e0f6e-0000-4000-8000-00000000dead"
    employee_user.save(update_fields=["external_id"])
    unknown = api_as(employee_user).get("/api/requester/infra/servers")

    assert unlinked.json() == unknown.json() == []
    assert not [c for c in cloud_sim.calls if "servers" in c]


def test_staff_see_every_project(api_as, technician_user, cloud_sim: CloudSim):
    client = api_as(technician_user)

    assert names(client.get("/api/infra/projects")) == {
        p.name for p in cloud_sim.cloud.projects.values()
    }
    assert "web-03" in names(client.get("/api/infra/servers"))
    web = client.get(f"/api/infra/servers/{cloud_sim.id_of('servers', 'web-03')}")
    assert web.status_code == 200
    assert not [c for c in cloud_sim.calls if "role_assignments" in c]


# ── refusals ──


def test_staff_and_customer_routers_each_require_their_own_single_permission(
    api_as, customer, technician_user, manager_user, cloud_sim
):
    customer_on_staff = api_as(customer).get("/api/infra/servers")
    staff_on_customer = api_as(technician_user).get("/api/requester/infra/servers")
    manager_on_staff = api_as(manager_user).get("/api/infra/servers")
    manager_on_customer = api_as(manager_user).get("/api/requester/infra/servers")

    assert customer_on_staff.status_code == 403
    assert customer_on_staff.json()["details"]["permission"] == "urn:smart-ticket:perm:infra:read"
    assert staff_on_customer.status_code == 403
    assert (
        staff_on_customer.json()["details"]["permission"] == "urn:smart-ticket:perm:infra:read:own"
    )
    assert manager_on_staff.status_code == manager_on_customer.status_code == 403


def test_an_unavailable_cloud_api_is_424_with_a_recorded_row(
    api_as, technician_user, cloud_sim: CloudSim
):
    cloud_sim.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    reply = api_as(technician_user).get("/api/infra/servers")

    assert reply.status_code == 424
    assert reply.json()["code"] == "infra_backend_unavailable"
    row = InfraQuery.objects.get()
    assert (row.backend, row.outcome, row.rows) == ("cloud", "backend_unavailable", 0)


def test_an_unreachable_cloud_is_424(api_as, technician_user, settings, monkeypatch):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings.OPENSTACK_AUTH_URL = "http://cloud.invalid/identity/v3"
    monkeypatch.setattr(inventory, "openstack", lambda: OpenStack(mock_http(refuse)))

    reply = api_as(technician_user).get("/api/infra/volumes")

    assert reply.status_code == 424
    assert InfraQuery.objects.get().outcome == "backend_unavailable"


def test_an_unreadable_cloud_answer_is_424(api_as, technician_user, settings, monkeypatch):
    settings.OPENSTACK_AUTH_URL = "http://cloud.test/identity/v3"
    cloud = FakeCloud({"/compute/servers/detail": [httpx.Response(200, json={"servers": [{}]})]})
    monkeypatch.setattr(inventory, "openstack", lambda: OpenStack(cloud.http()))

    reply = api_as(technician_user).get("/api/infra/servers")

    assert reply.status_code == 424
    assert InfraQuery.objects.get().outcome == "backend_unavailable"


def test_an_unreachable_alertmanager_is_424(
    api_as, technician_user, cloud_sim, alertmanager: FakeAlertmanager
):
    alertmanager.error = httpx.ReadTimeout("timed out")

    reply = api_as(technician_user).get("/api/infra/alerts")

    assert reply.status_code == 424
    row = InfraQuery.objects.get()
    assert (row.backend, row.outcome) == ("alertmanager", "backend_unavailable")


# ── masking ──


def test_ner_failure_withholds_alert_text_but_keeps_counts(
    api_as, technician_user, cloud_sim, alertmanager: FakeAlertmanager, ner
):
    alertmanager.alerts = [alert("CloudServerDown", "p1", "db-01 does not answer")] * 2
    ner(lambda text: (_ for _ in ()).throw(NERError("down")))

    reply = api_as(technician_user).get("/api/infra/alerts")

    assert reply.status_code == 200
    assert [a["summary"] for a in reply.json()] == [WITHHELD, WITHHELD]
    assert [a["name"] for a in reply.json()] == ["CloudServerDown"] * 2
    row = InfraQuery.objects.get()
    assert (row.rows, row.withheld) == (2, 2)


def test_critical_pii_in_an_alert_is_withheld(
    api_as, technician_user, cloud_sim, alertmanager: FakeAlertmanager, ner
):
    alertmanager.alerts = [alert("LoginFailed", "p1", "password: hunter2 rejected")]

    reply = api_as(technician_user).get("/api/infra/alerts")

    assert reply.json()[0]["summary"] == WITHHELD


def test_pii_in_server_metadata_is_masked(api_as, technician_user, cloud_sim: CloudSim, ner):
    db = cloud_sim.cloud.servers[cloud_sim.id_of("servers", "db-01")]
    db.workload = "owner lan.nt@saomai.vn"

    reply = api_as(technician_user).get(f"/api/infra/servers/{db.id}")

    assert "lan.nt@saomai.vn" not in reply.content.decode()
    assert reply.json()["attachments"][0]["device"] == "/dev/vdb"


# ── alerts and silences ──


def test_a_customer_sees_only_their_projects_alerts(
    api_as, customer, cloud_sim: CloudSim, alertmanager: FakeAlertmanager, ner
):
    prod = cloud_sim.id_of("projects", "saomai-prod")
    hbr = cloud_sim.id_of("projects", "hbr-web")
    alertmanager.alerts = [
        alert("CloudServerDown", prod, "db-01 down"),
        alert("CloudServerDown", hbr, "web-03 down"),
        alert("HypervisorDown", None, "compute-02 down"),
    ]

    mine = api_as(customer).get("/api/requester/infra/alerts")

    assert [a["project_id"] for a in mine.json()] == [prod]


def test_staff_see_alerts_tied_to_no_project(
    api_as, technician_user, cloud_sim, alertmanager: FakeAlertmanager, ner
):
    alertmanager.alerts = [alert("HypervisorDown", None, "compute-02 down")]

    reply = api_as(technician_user).get("/api/infra/alerts")

    assert [a["name"] for a in reply.json()] == ["HypervisorDown"]


def test_a_silence_matching_projects_by_regex_is_hidden_from_customers(
    api_as, customer, cloud_sim: CloudSim, alertmanager: FakeAlertmanager, ner
):
    prod = cloud_sim.id_of("projects", "saomai-prod")

    def silence(id_: str, value: str, is_regex: bool) -> dict[str, Any]:
        return {
            "id": id_,
            "status": {"state": "active"},
            "matchers": [{"name": "project", "value": value, "isRegex": is_regex, "isEqual": True}],
            "createdBy": "duc.tm",
            "comment": "maintenance",
            "startsAt": "2026-11-26T09:00:00Z",
            "endsAt": "2026-11-26T10:00:00Z",
        }

    alertmanager.silences = [silence("s1", prod, False), silence("s2", ".*", True)]

    reply = api_as(customer).get("/api/requester/infra/alerts/silences")

    assert [s["id"] for s in reply.json()] == ["s1"]


# ── the record ──


def test_every_read_writes_one_row_naming_who_and_what(
    api_as, technician_user, cloud_sim: CloudSim
):
    api_as(technician_user).get("/api/infra/servers")

    row = InfraQuery.objects.get()
    assert (row.actor, row.via, row.agent_turn) == (technician_user, "human", None)
    assert (row.backend, row.kind, row.outcome, row.projects) == ("cloud", "resource", "ok", ["*"])
    assert row.rows == len(cloud_sim.cloud.servers)
    assert "GET compute /servers/detail?all_tenants=True" in row.compiled


def test_an_agents_read_names_its_turn(customer, cloud_sim: CloudSim):
    reply = as_agent(customer, "list_my_servers").get("/api/requester/infra/servers")

    assert reply.status_code == 200
    row = InfraQuery.objects.get()
    assert row.via == "agent"
    assert row.agent_turn is not None
    assert row.projects == sorted(
        cloud_sim.id_of("projects", n) for n in ("saomai-prod", "saomai-staging")
    )


def test_a_refused_read_is_recorded(api_as, customer, cloud_sim: CloudSim):
    api_as(customer).get(f"/api/requester/infra/servers/{cloud_sim.id_of('servers', 'web-03')}")

    row = InfraQuery.objects.get()
    assert (row.outcome, row.refusal, row.rows) == ("refused", "infra_not_found", 0)


def test_a_network_shows_its_subnets_ports_and_groups(
    api_as, technician_user, cloud_sim: CloudSim, ner
):
    hbr = cloud_sim.id_of("networks", "hbr-web-net")

    reply = api_as(technician_user).get(f"/api/infra/networks/{hbr}").json()

    assert reply["subnets"][0]["cidr"]
    assert {p["device_id"] for p in reply["ports"]} >= {cloud_sim.id_of("servers", "web-03")}
    ssh = [r for g in reply["security_groups"] for r in g["rules"] if r["port_min"] == 22]
    assert any(r["remote_ip_prefix"] == "0.0.0.0/0" for r in ssh)
