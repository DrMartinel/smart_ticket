"""A caller's reads of the cloud's resources and alerts (F17 §h.1): within their scope, free text
masked, and each read recorded as one `infra_queries` row (BR-F17-10)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, Self
from urllib.parse import urlencode

from apps.accounts.permissions import Caller
from apps.infra.models import InfraBackend, InfraOutcome, InfraQuery, InfraQueryKind, InfraVia
from apps.infra.clients.backends import (
    Alertmanager,
    BackendNotFound,
    BackendUnavailable,
    OpenStack,
    Params,
    alertmanager,
    openstack,
)
from apps.infra.domain.resources import Alert, Network, Port, Project, SecurityGroup, Server
from apps.infra.domain.resources import Silence, Subnet, Volume
from apps.infra.services.scope import InfraScope
from apps.infra.domain.untrusted import MaskedTexts
from apps.infra.domain.vocabulary import InfraError, InfraRefusal

logger = logging.getLogger(__name__)

# What a backend's answer that can't be parsed raises.
UNREADABLE = (KeyError, TypeError, ValueError)


class HasFreeText(Protocol):
    def free_text(self) -> list[str]: ...

    def with_free_text(self, texts: list[str]) -> Self: ...


@dataclass
class Read:
    """One read as it runs: the calls it made, its rows and the texts it withheld."""

    backend: InfraBackend
    projects: list[str]
    calls: list[str] = field(default_factory=list)
    rows: int = 0
    withheld: int = 0


class Inventory:
    """The cloud's projects, servers, volumes, networks, alerts and silences, as one caller
    may see them."""

    def __init__(
        self, caller: Caller, scope: InfraScope, cloud: OpenStack, alerts: Alertmanager
    ) -> None:
        self.caller = caller
        self.scope = scope
        self.cloud = cloud
        self.alertmanager = alerts

    @classmethod
    def for_all(cls, caller: Caller) -> Inventory:
        """Staff inventory across every cloud project."""
        return cls(caller, InfraScope.all(), openstack(), alertmanager())

    @classmethod
    def for_own(cls, caller: Caller) -> Inventory:
        """Customer inventory narrowed to the caller's Keystone projects; refuses with
        `infra_scope_unavailable` when Keystone can't answer, never widening scope."""
        cloud = openstack()
        started = time.monotonic()
        try:
            scope = InfraScope.own(caller, cloud)
        except BackendUnavailable as e:
            logger.warning("infra: scope lookup failed: %s", e)
            cls.record(
                caller,
                Read(InfraBackend.CLOUD, [], ["GET identity /role_assignments"]),
                InfraOutcome.SCOPE_UNAVAILABLE,
                InfraRefusal.SCOPE_UNAVAILABLE,
                started,
            )
            raise InfraError(
                InfraRefusal.SCOPE_UNAVAILABLE, "the cloud can't say which projects are yours"
            ) from e
        return cls(caller, scope, cloud, alertmanager())

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
            return self.shown(read, [Project.of(p) for p in found])

    # ── servers ──

    def servers(self, project_id: str | None) -> list[Server]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            found = self.per_project(read, "compute", "/servers/detail", "servers", wanted)
            return self.shown(read, self.reachable([Server.of(s) for s in found]))

    def server(self, server_id: str) -> Server:
        with self.read(InfraBackend.CLOUD, self.scope.narrowed_to(None)) as read:
            server = Server.of(self.get(read, "compute", f"/servers/{server_id}")["server"])
            self.require_reach(server.project_id, "server", server_id)
            attached = self.get(read, "compute", f"/servers/{server_id}/os-volume_attachments")
            return self.shown(read, [server.with_attachments(attached["volumeAttachments"])])[0]

    # ── volumes ──

    def volumes(self, project_id: str | None) -> list[Volume]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            found = self.per_project(read, "volumev3", "/volumes/detail", "volumes", wanted)
            return self.shown(read, self.reachable([Volume.of(v) for v in found]))

    def volume(self, volume_id: str) -> Volume:
        with self.read(InfraBackend.CLOUD, self.scope.narrowed_to(None)) as read:
            volume = Volume.of(self.get(read, "volumev3", f"/volumes/{volume_id}")["volume"])
            self.require_reach(volume.project_id, "volume", volume_id)
            return self.shown(read, [volume])[0]

    # ── networks ──

    def networks(self, project_id: str | None) -> list[Network]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.CLOUD, wanted) as read:
            found = self.per_project(read, "network", "/v2.0/networks", "networks", wanted)
            return self.shown(read, self.reachable([Network.of(n) for n in found]))

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
            return self.shown(read, [network])[0]

    # ── alerts ──

    def alerts(self, project_id: str | None) -> list[Alert]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.ALERTMANAGER, wanted) as read:
            read.calls.append("GET /api/v2/alerts")
            found = [Alert.of(a) for a in self.alertmanager.get("/alerts")]
            return self.shown(read, [a for a in found if self.covers(wanted, a.project_id)])

    def silences(self, project_id: str | None) -> list[Silence]:
        wanted = self.scope.narrowed_to(project_id)
        with self.read(InfraBackend.ALERTMANAGER, wanted) as read:
            read.calls.append("GET /api/v2/silences")
            found = [Silence.of(s) for s in self.alertmanager.get("/silences")]
            return self.shown(read, [s for s in found if self.covers(wanted, s.project_id)])

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

    def shown[T: HasFreeText](self, read: Read, items: list[T]) -> list[T]:
        """`items` with their free text masked or withheld, counted on the read."""
        texts = [t for item in items for t in item.free_text()]
        masked = MaskedTexts.of(texts)
        read.rows, read.withheld = len(items), read.withheld + masked.withheld
        shown, at = [], 0
        for item in items:
            n = len(item.free_text())
            shown.append(item.with_free_text(masked.texts[at : at + n]))
            at += n
        return shown

    @contextmanager
    def read(self, backend: InfraBackend, projects: frozenset[str] | None) -> Iterator[Read]:
        """Runs one read and records it, turning a backend's failure into a coded refusal."""
        read = Read(backend, InfraScope.listing(projects))
        started = time.monotonic()
        try:
            yield read
        except BackendNotFound as e:
            self.record(self.caller, read, InfraOutcome.REFUSED, InfraRefusal.NOT_FOUND, started)
            raise InfraError(InfraRefusal.NOT_FOUND, "no such resource") from e
        except (BackendUnavailable, *UNREADABLE) as e:
            logger.warning("infra: %s read failed: %s", backend.value, e)
            self.record(
                self.caller,
                read,
                InfraOutcome.BACKEND_UNAVAILABLE,
                InfraRefusal.BACKEND_UNAVAILABLE,
                started,
            )
            raise InfraError(
                InfraRefusal.BACKEND_UNAVAILABLE, f"{backend.value} did not answer"
            ) from e
        else:
            self.record(self.caller, read, InfraOutcome.OK, None, started)

    @staticmethod
    def record(
        caller: Caller,
        read: Read,
        outcome: InfraOutcome,
        refusal: InfraRefusal | None,
        started: float,
    ) -> InfraQuery:
        return InfraQuery.objects.create(
            actor=caller.user,
            via=(InfraVia.AGENT if caller.agent else InfraVia.HUMAN).value,
            agent_turn_id=caller.agent.turn if caller.agent else None,
            backend=read.backend.value,
            kind=InfraQueryKind.RESOURCE.value,
            compiled="\n".join(read.calls),
            projects=read.projects,
            outcome=outcome.value,
            refusal=refusal.value if refusal else None,
            duration_ms=int((time.monotonic() - started) * 1000),
            rows=read.rows if outcome is InfraOutcome.OK else 0,
            withheld=read.withheld,
        )
