"""Neutron's security-group rules, and the simulator's fault and reset routes."""

from __future__ import annotations

from typing import Any

from cloud_sim.testing import Sim


def _group(sim: Sim) -> str:
    project = sim.id_of("project", "saomai-prod")
    reply = sim.client.get(
        "/network/v2.0/security-groups", params={"project_id": project}, headers=sim.headers
    )
    return next(g["id"] for g in reply.json()["security_groups"] if g["name"] == "db")


def _rule(group: str, **overrides: Any) -> dict[str, Any]:
    rule = {
        "security_group_id": group,
        "direction": "ingress",
        "protocol": "tcp",
        "port_range_min": 22,
        "port_range_max": 22,
        "remote_ip_prefix": "10.10.0.0/24",
    }
    return {"security_group_rule": {**rule, **overrides}}


def test_a_rule_is_added_and_removed(sim: Sim) -> None:
    group = _group(sim)

    added = sim.client.post(
        "/network/v2.0/security-group-rules", json=_rule(group), headers=sim.headers
    )
    rule_id = added.json()["security_group_rule"]["id"]
    removed = sim.client.delete(
        f"/network/v2.0/security-group-rules/{rule_id}", headers=sim.headers
    )

    assert added.status_code == 201
    assert removed.status_code == 204
    assert (
        sim.client.delete(
            f"/network/v2.0/security-group-rules/{rule_id}", headers=sim.headers
        ).status_code
        == 404
    )


def test_a_duplicate_rule_is_409(sim: Sim) -> None:
    group = _group(sim)
    sim.client.post("/network/v2.0/security-group-rules", json=_rule(group), headers=sim.headers)

    reply = sim.client.post(
        "/network/v2.0/security-group-rules", json=_rule(group), headers=sim.headers
    )

    assert reply.status_code == 409
    assert reply.json()["NeutronError"]["type"] == "SecurityGroupRuleExists"


def test_an_invalid_rule_is_400(sim: Sim) -> None:
    group = _group(sim)
    for bad in (
        {"port_range_min": 70000},
        {"direction": "sideways"},
        {"remote_ip_prefix": "not-an-ip"},
        {"port_range_min": 30, "port_range_max": 20},
    ):
        reply = sim.client.post(
            "/network/v2.0/security-group-rules", json=_rule(group, **bad), headers=sim.headers
        )
        assert reply.status_code == 400, bad


def test_each_server_has_one_port_on_its_projects_network(sim: Sim) -> None:
    server = sim.id_of("server", "db-01")

    ports = sim.client.get(
        "/network/v2.0/ports", params={"device_id": server}, headers=sim.headers
    ).json()["ports"]

    assert len(ports) == 1
    assert ports[0]["network_id"] == sim.id_of("network", "saomai-prod-net")
    assert ports[0]["fixed_ips"][0]["ip_address"] == "10.10.0.11"


def test_a_fault_on_an_unknown_resource_is_404(sim: Sim) -> None:
    reply = sim.client.post("/sim/faults", json={"kind": "disk_full", "target_id": "nope"})

    assert reply.status_code == 404


def test_a_fault_on_the_wrong_kind_of_resource_is_404(sim: Sim) -> None:
    reply = sim.client.post(
        "/sim/faults", json={"kind": "disk_full", "target_id": sim.id_of("volume", "vol-db-01")}
    )

    assert reply.status_code == 404


def test_api_slow_needs_a_delay(sim: Sim) -> None:
    assert sim.client.post("/sim/faults", json={"kind": "api_slow"}).status_code == 400


def test_an_unavailable_api_answers_503_but_the_simulator_still_answers(sim: Sim) -> None:
    sim.client.post("/sim/faults", json={"kind": "api_unavailable"})

    assert sim.client.get("/compute/v2.1/servers/detail", headers=sim.headers).status_code == 503
    assert sim.client.get("/sim/health").status_code == 200
    assert sim.client.get("/metrics").status_code == 200


def test_a_removed_fault_stops(sim: Sim) -> None:
    fault = sim.client.post("/sim/faults", json={"kind": "api_unavailable"}).json()["fault"]

    sim.client.delete(f"/sim/faults/{fault['id']}")

    assert sim.client.get("/compute/v2.1/servers/detail", headers=sim.headers).status_code == 200
    assert sim.client.get("/sim/faults").json()["faults"] == []


def test_reset_clears_faults_and_changes(sim: Sim) -> None:
    server = sim.id_of("server", "db-01")
    sim.client.post("/sim/faults", json={"kind": "server_hung", "target_id": server})
    sim.client.post(
        f"/compute/v2.1/servers/{server}/action", json={"os-stop": None}, headers=sim.headers
    )

    assert sim.client.post("/sim/reset").status_code == 204

    assert sim.client.get("/sim/faults").json()["faults"] == []
    assert (
        sim.client.get(f"/compute/v2.1/servers/{server}", headers=sim.headers).json()["server"][
            "status"
        ]
        == "ACTIVE"
    )
