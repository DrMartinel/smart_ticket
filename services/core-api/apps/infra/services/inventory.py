"""A caller's reads of the cloud's resources and alerts (F17 §h.1): within their scope, free text
masked, and each read recorded as one `infra_queries` row (BR-F17-10)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from urllib.parse import urlencode

from apps.accounts.permissions import Caller
from apps.infra.clients.backends import (
    Alertmanager,
    BackendNotFound,
    OpenStack,
    Params,
    alertmanager,
    openstack,
)
from apps.infra.domain.resources import Alert, AlertResource, Network, Port, Project
from apps.infra.domain.resources import SecurityGroup, Server
from apps.infra.domain.resources import Silence, Subnet, Volume
from apps.infra.models import InfraBackend, InfraQueryKind
from apps.infra.services.recording import QueryLog, Read
from apps.infra.services.scope import InfraScope


class Inventory:
    """The cloud's projects, servers, volumes, networks, alerts and silences, as one caller
    may see them."""

    def __init__(
        self, log: QueryLog, scope: InfraScope, cloud: OpenStack, alerts: Alertmanager
    ) -> None:
        self.log = log
        self.scope = scope
        self.cloud = cloud
        self.alertmanager = alerts

    @classmethod
    def for_all(cls, caller: Caller) -> Inventory:
        """Staff inventory across every cloud project."""
        return cls(QueryLog.of(caller), InfraScope.all(), openstack(), alertmanager())

    @classmethod
    def for_own(cls, caller: Caller) -> Inventory:
        """Customer inventory narrowed to the caller's Keystone projects."""
        log, cloud = QueryLog.of(caller), openstack()
        return cls(log, log.own_scope(cloud), cloud, alertmanager())

    # ── projects ──

    def projects(self) -> list[Project]:
        wanted = self.scope.narrowed_to(None)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            if wanted is None:
                found = self.get(read, "identity", "/projects")["projects"]
            else:
                found = [
                    self.get(read, "identity", f"/projects/{p}")["project"] for p in sorted(wanted)
                ]
            return read.shown([Project.of(p) for p in found])

    # ── servers ──

    def servers(self, project_id: str | None) -> list[Server]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            found = self.per_project(read, "compute", "/servers/detail", "servers", wanted)
            return read.shown(self.reachable([Server.of(s) for s in found]))

    def server(self, server_id: str) -> Server:
        with self.read(InfraBackend.CLOUD, self.scope.narrowed_to(None)) as read:
            server = Server.of(self.get(read, "compute", f"/servers/{server_id}")["server"])
            self.require_reach(server.project_id, "server", server_id)
            attached = self.get(read, "compute", f"/servers/{server_id}/os-volume_attachments")
            return read.shown([server.with_attachments(attached["volumeAttachments"])])[0]

    # ── volumes ──

    def volumes(self, project_id: str | None) -> list[Volume]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            found = self.per_project(read, "volumev3", "/volumes/detail", "volumes", wanted)
            return read.shown(self.reachable([Volume.of(v) for v in found]))

    def volume(self, volume_id: str) -> Volume:
        with self.read(InfraBackend.CLOUD, self.scope.narrowed_to(None)) as read:
            volume = Volume.of(self.get(read, "volumev3", f"/volumes/{volume_id}")["volume"])
            self.require_reach(volume.project_id, "volume", volume_id)
            return read.shown([volume])[0]

    # ── networks ──

    def networks(self, project_id: str | None) -> list[Network]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            found = self.per_project(read, "network", "/v2.0/networks", "networks", wanted)
            return read.shown(self.reachable([Network.of(n) for n in found]))

    def network(self, network_id: str) -> Network:
        """The network with its subnets, ports and its project's security groups."""
        with self.read(InfraBackend.CLOUD, self.scope.narrowed_to(None)) as read:
            network = Network.of(
                self.get(read, "network", f"/v2.0/networks/{network_id}")["network"]
            )
            self.require_reach(network.project_id, "network", network_id)
            on_network = {"network_id": network_id}
            subnets = self.get(read, "network", "/v2.0/subnets", on_network)["subnets"]
            ports = self.get(read, "network", "/v2.0/ports", on_network)["ports"]
            groups = self.get(
                read, "network", "/v2.0/security-groups", {"project_id": network.project_id}
            )["security_groups"]
            network = replace(
                network,
                subnets=[Subnet.of(s) for s in subnets],
                ports=[Port.of(p) for p in ports],
                security_groups=[SecurityGroup.of(g) for g in groups],
            )
            return read.shown([network])[0]

    # ── security groups ──

    def security_group(self, group_id: str) -> SecurityGroup:
        """The security group with its rules."""
        with self.read(InfraBackend.CLOUD, self.scope.narrowed_to(None)) as read:
            group = SecurityGroup.of(
                self.get(read, "network", f"/v2.0/security-groups/{group_id}")["security_group"]
            )
            self.require_reach(group.project_id, "security group", group_id)
            return read.shown([group])[0]

    # ── alerts ──

    def alerts(
        self,
        project_id: str | None,
        resource_kind: AlertResource | None = None,
        resource_id: str | None = None,
    ) -> list[Alert]:
        """The alerts in scope, narrowed to the resource `resource_kind` and `resource_id`
        name, each when given."""
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.ALERTMANAGER, wanted) as read:
            read.calls.append("GET /api/v2/alerts")
            found = [Alert.of(a) for a in self.alertmanager.get("/alerts")]
            return read.shown(
                [
                    a
                    for a in found
                    if self.covers(wanted, a.project_id) and a.is_about(resource_kind, resource_id)
                ]
            )

    def silences(self, project_id: str | None) -> list[Silence]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.ALERTMANAGER, wanted) as read:
            read.calls.append("GET /api/v2/silences")
            found = [Silence.of(s) for s in self.alertmanager.get("/silences")]
            return read.shown([s for s in found if self.covers(wanted, s.project_id)])

    # ── how a read runs ──

    def get(self, read: Read, service: str, path: str, params: Params | None = None) -> Any:
        """One call to the cloud, named in the read's record."""
        read.calls.append(f"GET {service} {path}" + (f"?{urlencode(params)}" if params else ""))
        return self.cloud.get(service, path, params)

    def per_project(
        self, read: Read, service: str, path: str, key: str, projects: frozenset[str] | None
    ) -> list[dict[str, Any]]:
        """A listing across every project, or one call per project in `projects`."""
        if projects is None:
            return list(self.get(read, service, path, {"all_tenants": True})[key])
        return [
            item
            for p in sorted(projects)
            for item in self.get(read, service, path, {"all_tenants": True, "project_id": p})[key]
        ]

    def reachable[T: (Server, Volume, Network)](self, items: list[T]) -> list[T]:
        return [i for i in items if self.scope.reaches(i.project_id)]

    def require_reach(self, project_id: str, kind: str, resource_id: str) -> None:
        """Refuses a resource outside the scope exactly as one that doesn't exist."""
        if not self.scope.reaches(project_id):
            raise BackendNotFound(f"{kind} {resource_id}")

    def covers(self, wanted: frozenset[str] | None, project_id: str | None) -> bool:
        """Whether an alert or silence of `project_id` is within `wanted`; one tied to no
        single project is for staff only."""
        if wanted is None:
            return True
        return project_id is not None and project_id in wanted

    @contextmanager
    def read(self, backend: InfraBackend, projects: frozenset[str] | None) -> Iterator[Read]:
        with self.log.read(backend, InfraQueryKind.RESOURCE, projects) as read:
            yield read
