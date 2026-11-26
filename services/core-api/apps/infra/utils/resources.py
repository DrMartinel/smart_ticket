"""The cloud's resources and alerts as core-api reads them, each from its backend's JSON, and
the free text in each that is masked before it is shown (F17 BR-F17-06). Parsing raises
`KeyError`, `TypeError` or `ValueError` on an answer it can't read."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Self


def _texts(mapping: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in mapping.items()}


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    domain_id: str

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Project:
        return cls(raw["id"], raw["name"], raw.get("domain_id") or "")

    def free_text(self) -> list[str]:
        return []

    def with_free_text(self, texts: list[str]) -> Self:
        return self


@dataclass(frozen=True)
class Address:
    network: str
    ip: str
    mac: str


@dataclass(frozen=True)
class Attachment:
    volume_id: str
    server_id: str
    device: str


@dataclass(frozen=True)
class Server:
    id: str
    name: str
    project_id: str
    status: str
    task_state: str | None
    host: str
    flavor: str
    vcpus: int
    ram_mb: int
    addresses: list[Address]
    volume_ids: list[str]
    security_groups: list[str]
    description: str
    metadata: dict[str, str]
    created: str
    updated: str
    attachments: list[Attachment] | None = None

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Server:
        flavor = raw.get("flavor") or {}
        return cls(
            id=raw["id"],
            name=raw["name"],
            project_id=raw["tenant_id"],
            status=raw["status"],
            task_state=raw.get("OS-EXT-STS:task_state"),
            host=raw.get("OS-EXT-SRV-ATTR:host") or "",
            flavor=flavor.get("original_name") or "",
            vcpus=int(flavor.get("vcpus") or 0),
            ram_mb=int(flavor.get("ram") or 0),
            addresses=[
                Address(network, a["addr"], a.get("OS-EXT-IPS-MAC:mac_addr") or "")
                for network, found in (raw.get("addresses") or {}).items()
                for a in found
            ],
            volume_ids=[v["id"] for v in raw.get("os-extended-volumes:volumes_attached") or []],
            security_groups=[g["name"] for g in raw.get("security_groups") or []],
            description=raw.get("description") or "",
            metadata=_texts(raw.get("metadata") or {}),
            created=raw.get("created") or "",
            updated=raw.get("updated") or "",
        )

    def with_attachments(self, raw: list[dict[str, Any]]) -> Server:
        return replace(
            self,
            attachments=[Attachment(a["volumeId"], self.id, a.get("device") or "") for a in raw],
        )

    def free_text(self) -> list[str]:
        return [self.description, *self.metadata.values()]

    def with_free_text(self, texts: list[str]) -> Self:
        description, *values = texts
        return replace(self, description=description, metadata=dict(zip(self.metadata, values)))


@dataclass(frozen=True)
class Volume:
    id: str
    name: str
    project_id: str
    status: str
    size_gb: int
    volume_type: str
    attachments: list[Attachment]
    description: str
    metadata: dict[str, str]
    created: str

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Volume:
        return cls(
            id=raw["id"],
            name=raw.get("name") or "",
            project_id=raw["os-vol-tenant-attr:tenant_id"],
            status=raw["status"],
            size_gb=int(raw.get("size") or 0),
            volume_type=raw.get("volume_type") or "",
            attachments=[
                Attachment(raw["id"], a["server_id"], a.get("device") or "")
                for a in raw.get("attachments") or []
            ],
            description=raw.get("description") or "",
            metadata=_texts(raw.get("metadata") or {}),
            created=raw.get("created_at") or "",
        )

    def free_text(self) -> list[str]:
        return [self.description, *self.metadata.values()]

    def with_free_text(self, texts: list[str]) -> Self:
        description, *values = texts
        return replace(self, description=description, metadata=dict(zip(self.metadata, values)))


@dataclass(frozen=True)
class Subnet:
    id: str
    name: str
    cidr: str
    ip_version: int

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Subnet:
        return cls(raw["id"], raw.get("name") or "", raw["cidr"], int(raw.get("ip_version") or 4))


@dataclass(frozen=True)
class Port:
    id: str
    device_id: str
    mac: str
    ips: list[str]
    status: str
    security_group_ids: list[str]

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Port:
        return cls(
            id=raw["id"],
            device_id=raw.get("device_id") or "",
            mac=raw.get("mac_address") or "",
            ips=[ip["ip_address"] for ip in raw.get("fixed_ips") or []],
            status=raw.get("status") or "",
            security_group_ids=list(raw.get("security_groups") or []),
        )


@dataclass(frozen=True)
class Rule:
    id: str
    direction: str
    ethertype: str
    protocol: str | None
    port_min: int | None
    port_max: int | None
    remote_ip_prefix: str | None

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Rule:
        return cls(
            id=raw["id"],
            direction=raw["direction"],
            ethertype=raw.get("ethertype") or "",
            protocol=raw.get("protocol"),
            port_min=raw.get("port_range_min"),
            port_max=raw.get("port_range_max"),
            remote_ip_prefix=raw.get("remote_ip_prefix"),
        )


@dataclass(frozen=True)
class SecurityGroup:
    id: str
    name: str
    description: str
    rules: list[Rule]

    @classmethod
    def of(cls, raw: dict[str, Any]) -> SecurityGroup:
        return cls(
            id=raw["id"],
            name=raw.get("name") or "",
            description=raw.get("description") or "",
            rules=[Rule.of(r) for r in raw.get("security_group_rules") or []],
        )


@dataclass(frozen=True)
class Network:
    id: str
    name: str
    project_id: str
    status: str
    description: str
    subnets: list[Subnet] | None = None
    ports: list[Port] | None = None
    security_groups: list[SecurityGroup] | None = None

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Network:
        return cls(
            id=raw["id"],
            name=raw.get("name") or "",
            project_id=raw["project_id"],
            status=raw.get("status") or "",
            description=raw.get("description") or "",
        )

    def free_text(self) -> list[str]:
        return [self.description, *(g.description for g in self.security_groups or [])]

    def with_free_text(self, texts: list[str]) -> Self:
        description, *groups = texts
        if self.security_groups is None:
            return replace(self, description=description)
        return replace(
            self,
            description=description,
            security_groups=[
                replace(g, description=d) for g, d in zip(self.security_groups, groups)
            ],
        )


@dataclass(frozen=True)
class Alert:
    name: str
    fingerprint: str
    state: str
    severity: str
    project_id: str | None
    labels: dict[str, str]
    summary: str
    description: str
    starts_at: str

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Alert:
        labels = _texts(raw["labels"])
        annotations = raw.get("annotations") or {}
        return cls(
            name=labels.get("alertname", ""),
            fingerprint=raw.get("fingerprint") or "",
            state=(raw.get("status") or {}).get("state") or "",
            severity=labels.get("severity", ""),
            project_id=labels.get("project"),
            labels=labels,
            summary=str(annotations.get("summary") or ""),
            description=str(annotations.get("description") or ""),
            starts_at=raw.get("startsAt") or "",
        )

    def free_text(self) -> list[str]:
        return [self.summary, self.description]

    def with_free_text(self, texts: list[str]) -> Self:
        summary, description = texts
        return replace(self, summary=summary, description=description)


@dataclass(frozen=True)
class Matcher:
    name: str
    value: str
    is_regex: bool
    is_equal: bool


@dataclass(frozen=True)
class Silence:
    id: str
    state: str
    matchers: list[Matcher]
    created_by: str
    comment: str
    starts_at: str
    ends_at: str

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Silence:
        return cls(
            id=raw["id"],
            state=(raw.get("status") or {}).get("state") or "",
            matchers=[
                Matcher(m["name"], m["value"], bool(m.get("isRegex")), m.get("isEqual", True))
                for m in raw["matchers"]
            ],
            created_by=raw.get("createdBy") or "",
            comment=raw.get("comment") or "",
            starts_at=raw.get("startsAt") or "",
            ends_at=raw.get("endsAt") or "",
        )

    @property
    def project_id(self) -> str | None:
        """The one project this silence is limited to, None if it isn't limited to one."""
        exact = {
            m.value for m in self.matchers if m.name == "project" and m.is_equal and not m.is_regex
        }
        return exact.pop() if len(exact) == 1 else None

    def free_text(self) -> list[str]:
        return [self.created_by, self.comment]

    def with_free_text(self, texts: list[str]) -> Self:
        created_by, comment = texts
        return replace(self, created_by=created_by, comment=comment)
