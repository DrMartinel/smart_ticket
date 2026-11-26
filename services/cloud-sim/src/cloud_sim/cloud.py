"""The simulated cloud's state: its inventory, the changes in progress and the faults injected."""

from __future__ import annotations

import ipaddress
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from cloud_sim.faults import TARGETS, Fault, FaultKind, Target
from cloud_sim.seed import Seed

Clock = Callable[[], datetime]

_RULE_DIRECTIONS = frozenset({"ingress", "egress"})
_RULE_ETHERTYPES = frozenset({"IPv4", "IPv6"})
_RULE_PROTOCOLS = frozenset({"tcp", "udp", "icmp"})
_DEVICE_LETTERS = "bcdefghijklmnopqrstuvwxyz"


class ServerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SHUTOFF = "SHUTOFF"
    REBOOT = "REBOOT"
    HARD_REBOOT = "HARD_REBOOT"
    ERROR = "ERROR"


class VolumeStatus(StrEnum):
    AVAILABLE = "available"
    IN_USE = "in-use"
    DETACHING = "detaching"


class NotFound(Exception):
    """No resource of this kind has this id."""

    def __init__(self, kind: str, id: str) -> None:
        super().__init__(f"{kind} {id} could not be found")
        self.kind = kind


class Conflict(Exception):
    """The resource's state does not allow the change."""


class Invalid(Exception):
    """The request names a change the cloud cannot make."""


@dataclass
class Domain:
    id: str
    name: str


@dataclass
class Project:
    id: str
    name: str
    domain_id: str
    environment: str


@dataclass
class User:
    id: str
    name: str
    domain_id: str
    subject: str | None
    password: str | None = None
    system_admin: bool = False


@dataclass
class Flavor:
    name: str
    vcpus: int
    ram_mb: int
    disk_gb: int


@dataclass
class Server:
    id: str
    name: str
    project_id: str
    host: str
    flavor: Flavor
    workload: str
    security_groups: list[str]
    port_id: str
    ip: str
    mac: str
    created: datetime
    calls: str | None = None
    status: ServerStatus = ServerStatus.ACTIVE
    # The status a reboot, start or stop ends in, and when.
    settles_to: ServerStatus | None = None
    settles_at: datetime | None = None
    updated: datetime | None = None

    @property
    def task_state(self) -> str | None:
        """The action in progress, as Nova names it."""
        if self.settles_at is None:
            return None
        if self.status is ServerStatus.REBOOT:
            return "rebooting"
        if self.status is ServerStatus.HARD_REBOOT:
            return "rebooting_hard"
        return "powering-off" if self.settles_to is ServerStatus.SHUTOFF else "powering-on"


@dataclass
class Volume:
    id: str
    name: str
    project_id: str
    size_gb: int
    iops_quota: int
    created: datetime
    server_id: str | None = None
    device: str | None = None
    status: VolumeStatus = VolumeStatus.AVAILABLE
    settles_at: datetime | None = None


@dataclass
class Network:
    id: str
    name: str
    project_id: str
    subnet_id: str
    cidr: str


@dataclass(frozen=True)
class Rule:
    id: str
    group_id: str
    project_id: str
    direction: str
    protocol: str | None
    port_min: int | None
    port_max: int | None
    remote_ip_prefix: str | None
    ethertype: str = "IPv4"

    def check(self) -> None:
        """Refuses a rule Neutron would refuse."""
        if not isinstance(self.direction, str) or self.direction not in _RULE_DIRECTIONS:
            raise Invalid(f"Invalid direction {self.direction!r}")
        if not isinstance(self.ethertype, str) or self.ethertype not in _RULE_ETHERTYPES:
            raise Invalid(f"Invalid ethertype {self.ethertype!r}")
        if self.protocol is not None and (
            not isinstance(self.protocol, str) or self.protocol not in _RULE_PROTOCOLS
        ):
            raise Invalid(f"Protocol {self.protocol!r} is not supported")
        for port in (self.port_min, self.port_max):
            if port is not None and (not _is_int(port) or not 1 <= port <= 65535):
                raise Invalid(f"Invalid port {port!r}")
        if (
            self.port_min is not None
            and self.port_max is not None
            and self.port_min > self.port_max
        ):
            raise Invalid("port_range_min must be <= port_range_max")
        if self.remote_ip_prefix is not None:
            try:
                ipaddress.ip_network(str(self.remote_ip_prefix))
            except ValueError:
                raise Invalid(f"Invalid remote_ip_prefix {self.remote_ip_prefix!r}") from None

    def same_as(self, other: Rule) -> bool:
        """Whether both rules allow the same traffic."""
        return (
            self.direction,
            self.protocol,
            self.port_min,
            self.port_max,
            self.remote_ip_prefix,
            self.ethertype,
        ) == (
            other.direction,
            other.protocol,
            other.port_min,
            other.port_max,
            other.remote_ip_prefix,
            other.ethertype,
        )


@dataclass
class SecurityGroup:
    id: str
    name: str
    project_id: str
    rules: list[Rule] = field(default_factory=list)


class Cloud:
    """The whole simulated cloud, safe to read and change from several threads."""

    def __init__(
        self,
        seed: Seed,
        *,
        clock: Clock,
        transition_sec: float,
        service_user: str,
        service_password: str,
    ) -> None:
        self._seed = seed
        self._clock = clock
        self._transition = timedelta(seconds=transition_sec)
        self._service = (service_user, service_password)
        self._lock = threading.RLock()
        self.region = seed.region
        self.reset()

    # --- reading ---

    @contextmanager
    def reading(self) -> Iterator[Cloud]:
        """Holds the cloud still, with every finished change applied, while the caller reads."""
        with self._lock:
            self.settle()
            yield self

    def now(self) -> datetime:
        """The simulator's current time."""
        return self._clock()

    def project(self, project_id: str) -> Project:
        return self._find(self.projects, project_id, "Project")

    def server(self, server_id: str) -> Server:
        return self._find(self.servers, server_id, "Server")

    def volume(self, volume_id: str) -> Volume:
        return self._find(self.volumes, volume_id, "Volume")

    def network(self, network_id: str) -> Network:
        return self._find(self.networks, network_id, "Network")

    def security_group(self, group_id: str) -> SecurityGroup:
        return self._find(self.security_groups, group_id, "Security group")

    def user(self, user_id: str) -> User:
        return self._find(self.users, user_id, "User")

    def rule(self, rule_id: str) -> Rule:
        for group in self.security_groups.values():
            for rule in group.rules:
                if rule.id == rule_id:
                    return rule
        raise NotFound("Security group rule", rule_id)

    def status_of(self, server: Server) -> ServerStatus:
        """The status Nova shows: a crash-looping server shows ERROR."""
        if server.status is ServerStatus.ACTIVE and self.has_fault(FaultKind.CRASH_LOOP, server.id):
            return ServerStatus.ERROR
        return server.status

    def is_up(self, server: Server) -> bool:
        """Whether the server's guest is running and answering."""
        return self.status_of(server) is ServerStatus.ACTIVE and not self.has_fault(
            FaultKind.SERVER_HUNG, server.id
        )

    def volumes_of(self, server: Server) -> list[Volume]:
        return [v for v in self.volumes.values() if v.server_id == server.id]

    def network_of(self, server: Server) -> Network:
        """The network the server's one port is on."""
        return next(n for n in self.networks.values() if n.project_id == server.project_id)

    def has_fault(self, kind: FaultKind, target_id: str | None) -> bool:
        return self.fault_on(kind, target_id) is not None

    def fault_on(self, kind: FaultKind, target_id: str | None) -> Fault | None:
        with self._lock:
            return next(
                (f for f in self.faults.values() if f.kind is kind and f.target_id == target_id),
                None,
            )

    def memberships(self, user_id: str) -> list[Project]:
        """The projects the user is a member of."""
        return [self.projects[p] for p in self.members.get(user_id, [])]

    def authenticate(self, username: str, password: str) -> User | None:
        """The service user, if the name and password are its own."""
        user = next((u for u in self.users.values() if u.name == username), None)
        if user is None or user.password is None or user.password != password:
            return None
        return user

    # --- changing ---

    def reboot(self, server_id: str, *, hard: bool) -> None:
        with self.reading():
            server = self.server(server_id)
            kind = "reboot" if not hard else "hard reboot"
            rebooting = {ServerStatus.REBOOT, ServerStatus.HARD_REBOOT}
            if not (hard and server.status in rebooting):
                _require_idle(server, kind)
            status = self.status_of(server)
            allowed = (
                {ServerStatus.ACTIVE, ServerStatus.ERROR, *rebooting}
                if hard
                else {ServerStatus.ACTIVE}
            )
            if status not in allowed:
                raise Conflict(f"Cannot '{kind}' instance {server_id} while it is in {status}")
            self._begin(
                server,
                ServerStatus.HARD_REBOOT if hard else ServerStatus.REBOOT,
                ServerStatus.ACTIVE,
            )
            if hard:
                self._clear(FaultKind.SERVER_HUNG, server.id)

    def start(self, server_id: str) -> None:
        with self.reading():
            server = self.server(server_id)
            _require_idle(server, "start")
            if server.status is not ServerStatus.SHUTOFF:
                raise Conflict(
                    f"Cannot 'start' instance {server_id} while it is in {server.status}"
                )
            self._clear(FaultKind.SERVER_HUNG, server.id)
            self._begin(server, ServerStatus.SHUTOFF, ServerStatus.ACTIVE)

    def stop(self, server_id: str) -> None:
        with self.reading():
            server = self.server(server_id)
            _require_idle(server, "stop")
            status = self.status_of(server)
            if status not in {ServerStatus.ACTIVE, ServerStatus.ERROR}:
                raise Conflict(f"Cannot 'stop' instance {server_id} while it is in {status}")
            self._begin(server, server.status, ServerStatus.SHUTOFF)

    def attach(self, volume_id: str, server_id: str) -> Volume:
        with self.reading():
            volume, server = self.volume(volume_id), self.server(server_id)
            if volume.project_id != server.project_id:
                raise Invalid("The volume and the server are in different projects")
            if volume.status is not VolumeStatus.AVAILABLE:
                raise Conflict(f"Volume {volume_id} status must be available, is {volume.status}")
            _require_idle(server, "attach_volume")
            if server.status not in {ServerStatus.ACTIVE, ServerStatus.SHUTOFF}:
                raise Conflict(
                    f"Cannot attach to instance {server_id} while it is in {server.status}"
                )
            taken = {v.device for v in self.volumes_of(server)}
            free = next(
                (f"/dev/vd{c}" for c in _DEVICE_LETTERS if f"/dev/vd{c}" not in taken), None
            )
            if free is None:
                raise Conflict(f"Instance {server_id} has no free device name")
            volume.server_id, volume.status, volume.device = server.id, VolumeStatus.IN_USE, free
            return volume

    def detach(self, volume_id: str, server_id: str) -> None:
        with self.reading():
            volume = self.volume(volume_id)
            server = self.server(server_id)
            if volume.server_id != server_id:
                raise NotFound("Volume attachment", volume_id)
            if volume.status is not VolumeStatus.IN_USE:
                raise Conflict(f"Volume {volume_id} status must be in-use, is {volume.status}")
            _require_idle(server, "detach_volume")
            volume.status, volume.settles_at = VolumeStatus.DETACHING, self.now() + self._transition

    def add_rule(self, group_id: str, values: dict[str, Any]) -> Rule:
        with self.reading():
            group = self.security_group(group_id)
            rule = Rule(
                id=str(uuid.uuid4()),
                group_id=group.id,
                project_id=group.project_id,
                direction=values.get("direction", ""),
                protocol=values.get("protocol"),
                port_min=values.get("port_range_min"),
                port_max=values.get("port_range_max"),
                remote_ip_prefix=values.get("remote_ip_prefix"),
                ethertype=values.get("ethertype", "IPv4"),
            )
            rule.check()
            if any(rule.same_as(r) for r in group.rules):
                raise Conflict(f"Security group rule already exists in group {group.id}")
            group.rules.append(rule)
            return rule

    def remove_rule(self, rule_id: str) -> None:
        with self.reading():
            rule = self.rule(rule_id)
            group = self.security_groups[rule.group_id]
            group.rules = [r for r in group.rules if r.id != rule_id]

    def add_fault(self, kind: FaultKind, target_id: str | None, params: dict[str, Any]) -> Fault:
        with self.reading():
            target = TARGETS[kind]
            if target is Target.API:
                target_id = None
            elif target_id is None:
                raise Invalid(f"{kind} needs a {target} id")
            else:
                finders: dict[Target, Callable[[str], object]] = {
                    Target.SERVER: self.server,
                    Target.VOLUME: self.volume,
                    Target.NETWORK: self.network,
                }
                finders[target](target_id)
            if kind is FaultKind.API_SLOW and not _is_number(params.get("delay_sec"), low=0):
                raise Invalid("api_slow needs a delay_sec of 0 or more")
            if (
                kind is FaultKind.PACKET_LOSS
                and "ratio" in params
                and not _is_number(params["ratio"], low=0, high=1)
            ):
                raise Invalid("packet_loss's ratio must be a number from 0 to 1")
            fault = Fault(str(uuid.uuid4()), kind, target_id, self.now(), dict(params))
            self.faults[fault.id] = fault
            return fault

    def remove_fault(self, fault_id: str) -> None:
        with self._lock:
            if self.faults.pop(fault_id, None) is None:
                raise NotFound("Fault", fault_id)

    def settle(self) -> None:
        """Applies every change whose time has come."""
        with self._lock:
            now = self.now()
            for server in self.servers.values():
                if server.settles_at is not None and server.settles_at <= now:
                    assert server.settles_to is not None
                    server.status, server.updated = server.settles_to, server.settles_at
                    server.settles_to = server.settles_at = None
            for volume in self.volumes.values():
                if (
                    volume.status is VolumeStatus.DETACHING
                    and volume.settles_at is not None
                    and volume.settles_at <= now
                ):
                    volume.status, volume.server_id, volume.device = (
                        VolumeStatus.AVAILABLE,
                        None,
                        None,
                    )
                    volume.settles_at = None

    def reset(self) -> None:
        """Puts the cloud back to its seed, with no faults."""
        with self._lock:
            self._load(self._seed)

    # --- internals ---

    def _begin(self, server: Server, during: ServerStatus, after: ServerStatus) -> None:
        server.status, server.settles_to = during, after
        server.settles_at = self.now() + self._transition
        server.updated = self.now()
        if not self._transition:
            self.settle()

    def _clear(self, kind: FaultKind, target_id: str) -> None:
        for fault_id in [
            f.id for f in self.faults.values() if f.kind is kind and f.target_id == target_id
        ]:
            del self.faults[fault_id]

    def _find[T](self, table: dict[str, T], id: str, kind: str) -> T:
        try:
            return table[id]
        except KeyError:
            raise NotFound(kind, id) from None

    def _load(self, seed: Seed) -> None:
        now = self.now()
        self.domains = {d.id: Domain(d.id, d.name) for d in seed.domains}
        domain_by_name = {d.name: d.id for d in seed.domains}
        self.projects = {
            p.id: Project(p.id, p.name, domain_by_name[p.domain], p.environment)
            for p in seed.projects
        }
        project_by_name = {p.name: p.id for p in seed.projects}
        service = User(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, "cloud-sim:service")),
            name=self._service[0],
            domain_id="default",
            subject=None,
            password=self._service[1],
            system_admin=True,
        )
        self.users = {service.id: service}
        self.members: dict[str, list[str]] = {}
        for u in seed.users:
            self.users[u.id] = User(u.id, u.name, domain_by_name[u.domain], u.subject)
            self.members[u.id] = [project_by_name[name] for name in u.member_of]
        self.networks = {
            n.id: Network(
                n.id,
                n.name,
                project_by_name[n.project],
                str(uuid.uuid5(uuid.UUID(n.id), "subnet")),
                n.cidr,
            )
            for n in seed.networks
        }
        self.security_groups = {
            g.id: SecurityGroup(
                g.id,
                g.name,
                project_by_name[g.project],
                [
                    Rule(
                        r.id,
                        g.id,
                        project_by_name[g.project],
                        r.direction,
                        r.protocol,
                        r.port_min,
                        r.port_max,
                        r.remote_ip_prefix,
                    )
                    for r in g.rules
                ],
            )
            for g in seed.security_groups
        }
        self.servers = {}
        for s in seed.servers:
            flavor = seed.flavors[s.flavor]
            port = uuid.uuid5(uuid.UUID(s.id), "port")
            self.servers[s.id] = Server(
                id=s.id,
                name=s.name,
                project_id=project_by_name[s.project],
                host=s.host,
                flavor=Flavor(s.flavor, flavor.vcpus, flavor.ram_mb, flavor.disk_gb),
                workload=s.workload,
                security_groups=s.security_groups,
                port_id=str(port),
                ip=s.ip,
                mac="fa:16:3e:" + ":".join(port.hex[i : i + 2] for i in (0, 2, 4)),
                created=now,
                calls=s.calls,
            )
        server_by_name = {s.name: s.id for s in seed.servers}
        self.volumes = {}
        for v in seed.volumes:
            volume = Volume(v.id, v.name, project_by_name[v.project], v.size_gb, v.iops_quota, now)
            if v.attached_to is not None:
                volume.server_id, volume.status = server_by_name[v.attached_to], VolumeStatus.IN_USE
                volume.device = "/dev/vdb"
            self.volumes[v.id] = volume
        self.faults: dict[str, Fault] = {}


def _require_idle(server: Server, action: str) -> None:
    """Refuses an action while another one is still running on the server."""
    if server.task_state is not None:
        raise Conflict(
            f"Cannot '{action}' instance {server.id} while it is in task_state {server.task_state}"
        )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object, *, low: float, high: float | None = None) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    return low <= value and (high is None or value <= high)
