"""Response shapes for the infra reads (F17 §h.1). Free text is already masked or withheld."""

from __future__ import annotations

from ninja import Schema


class ProjectOut(Schema):
    id: str
    name: str
    domain_id: str


class AddressOut(Schema):
    network: str
    ip: str
    mac: str


class AttachmentOut(Schema):
    volume_id: str
    server_id: str
    device: str


class ServerOut(Schema):
    id: str
    name: str
    project_id: str
    status: str
    task_state: str | None
    host: str
    flavor: str
    vcpus: int
    ram_mb: int
    addresses: list[AddressOut]
    volume_ids: list[str]
    security_groups: list[str]
    description: str
    metadata: dict[str, str]
    created: str
    updated: str


class ServerDetailOut(ServerOut):
    attachments: list[AttachmentOut]


class VolumeOut(Schema):
    id: str
    name: str
    project_id: str
    status: str
    size_gb: int
    volume_type: str
    attachments: list[AttachmentOut]
    description: str
    metadata: dict[str, str]
    created: str


class SubnetOut(Schema):
    id: str
    name: str
    cidr: str
    ip_version: int


class PortOut(Schema):
    id: str
    device_id: str
    mac: str
    ips: list[str]
    status: str
    security_group_ids: list[str]


class RuleOut(Schema):
    id: str
    direction: str
    ethertype: str
    protocol: str | None
    port_min: int | None
    port_max: int | None
    remote_ip_prefix: str | None


class SecurityGroupOut(Schema):
    id: str
    name: str
    description: str
    rules: list[RuleOut]


class NetworkOut(Schema):
    id: str
    name: str
    project_id: str
    status: str
    description: str


class NetworkDetailOut(NetworkOut):
    subnets: list[SubnetOut]
    ports: list[PortOut]
    security_groups: list[SecurityGroupOut]


class AlertOut(Schema):
    name: str
    fingerprint: str
    state: str
    severity: str
    project_id: str | None
    labels: dict[str, str]
    summary: str
    description: str
    starts_at: str


class MatcherOut(Schema):
    name: str
    value: str
    is_regex: bool
    is_equal: bool


class SilenceOut(Schema):
    id: str
    state: str
    project_id: str | None
    matchers: list[MatcherOut]
    created_by: str
    comment: str
    starts_at: str
    ends_at: str
