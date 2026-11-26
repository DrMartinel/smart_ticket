"""Neutron's v2.0 API, the parts core-api uses: networks, subnets, ports, security groups and their rules."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from cloud_sim.api.errors import neutron_error
from cloud_sim.api.identity import Admin, cloud_of
from cloud_sim.cloud import Cloud, Conflict, Invalid, Network, NotFound, Rule, SecurityGroup, Server

router = APIRouter(prefix="/network/v2.0")


@router.get("/networks")
def list_networks(request: Request, _: Admin, project_id: str | None = None) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        return {
            "networks": [
                network_view(n)
                for n in cloud.networks.values()
                if project_id is None or n.project_id == project_id
            ]
        }


@router.get("/networks/{network_id}")
def get_network(request: Request, network_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        try:
            return {"network": network_view(cloud.network(network_id))}
        except NotFound as e:
            raise neutron_error(404, "NetworkNotFound", str(e)) from None


@router.get("/subnets")
def list_subnets(
    request: Request, _: Admin, network_id: str | None = None, project_id: str | None = None
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        networks = [
            n
            for n in cloud.networks.values()
            if (network_id is None or n.id == network_id)
            and (project_id is None or n.project_id == project_id)
        ]
        return {"subnets": [subnet_view(n) for n in networks]}


@router.get("/ports")
def list_ports(
    request: Request,
    _: Admin,
    device_id: str | None = None,
    network_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        servers = [
            s
            for s in cloud.servers.values()
            if (device_id is None or s.id == device_id)
            and (network_id is None or cloud.network_of(s).id == network_id)
            and (project_id is None or s.project_id == project_id)
        ]
        return {"ports": [port_view(cloud, s) for s in servers]}


@router.get("/security-groups")
def list_security_groups(
    request: Request, _: Admin, project_id: str | None = None
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        return {
            "security_groups": [
                group_view(g)
                for g in cloud.security_groups.values()
                if project_id is None or g.project_id == project_id
            ]
        }


@router.get("/security-groups/{group_id}")
def get_security_group(request: Request, group_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        try:
            return {"security_group": group_view(cloud.security_group(group_id))}
        except NotFound as e:
            raise neutron_error(404, "SecurityGroupNotFound", str(e)) from None


@router.get("/security-group-rules")
def list_rules(request: Request, _: Admin, security_group_id: str | None = None) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        rules = [
            rule_view(r)
            for g in cloud.security_groups.values()
            for r in g.rules
            if security_group_id is None or g.id == security_group_id
        ]
        return {"security_group_rules": rules}


@router.post("/security-group-rules", status_code=201)
def add_rule(request: Request, body: dict[str, Any], _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    values = body.get("security_group_rule") or {}
    group_id = str(values.get("security_group_id", ""))
    try:
        rule = cloud.add_rule(group_id, values)
    except NotFound as e:
        raise neutron_error(404, "SecurityGroupNotFound", str(e)) from None
    except Invalid as e:
        raise neutron_error(400, "SecurityGroupRuleInvalid", str(e)) from None
    except Conflict as e:
        raise neutron_error(409, "SecurityGroupRuleExists", str(e)) from None
    return {"security_group_rule": rule_view(rule)}


@router.delete("/security-group-rules/{rule_id}", status_code=204)
def remove_rule(request: Request, rule_id: str, _: Admin) -> Response:
    try:
        cloud_of(request).remove_rule(rule_id)
    except NotFound as e:
        raise neutron_error(404, "SecurityGroupRuleNotFound", str(e)) from None
    return Response(status_code=204)


def network_view(network: Network) -> dict[str, Any]:
    return {
        "id": network.id,
        "name": network.name,
        "project_id": network.project_id,
        "status": "ACTIVE",
        "admin_state_up": True,
        "subnets": [network.subnet_id],
        "mtu": 1450,
    }


def subnet_view(network: Network) -> dict[str, Any]:
    return {
        "id": network.subnet_id,
        "name": f"{network.name}-subnet",
        "network_id": network.id,
        "project_id": network.project_id,
        "cidr": network.cidr,
        "ip_version": 4,
        "enable_dhcp": True,
    }


def port_view(cloud: Cloud, server: Server) -> dict[str, Any]:
    network = cloud.network_of(server)
    groups = [
        g.id
        for g in cloud.security_groups.values()
        if g.project_id == server.project_id and g.name in server.security_groups
    ]
    return {
        "id": server.port_id,
        "name": "",
        "network_id": network.id,
        "project_id": server.project_id,
        "device_id": server.id,
        "device_owner": "compute:nova",
        "mac_address": server.mac,
        "fixed_ips": [{"subnet_id": network.subnet_id, "ip_address": server.ip}],
        "status": "ACTIVE" if cloud.is_up(server) else "DOWN",
        "admin_state_up": True,
        "security_groups": groups,
    }


def group_view(group: SecurityGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "project_id": group.project_id,
        "security_group_rules": [rule_view(r) for r in group.rules],
    }


def rule_view(rule: Rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "security_group_id": rule.group_id,
        "project_id": rule.project_id,
        "direction": rule.direction,
        "ethertype": rule.ethertype,
        "protocol": rule.protocol,
        "port_range_min": rule.port_min,
        "port_range_max": rule.port_max,
        "remote_ip_prefix": rule.remote_ip_prefix,
    }
