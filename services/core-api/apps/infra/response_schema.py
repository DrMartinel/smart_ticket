"""Response shapes for the infra reads (F17 §h.1), where free text is already masked or
withheld, for the customer and cue routes (F17 §o.9), and for the changes (F17 §h.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Schema

from apps.infra.domain.changes import InfraChange, InfraResource
from apps.infra.domain.vocabulary import CueRunOutcome, CueStatus, ResourceKind, ResourceSource
from apps.infra.models import CueRun, Customer, CustomerTier, TicketCue


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


class MetricEntryOut(Schema):
    name: str
    kind: str
    help: str
    labels: list[str]


class DatasetEntryOut(Schema):
    name: str
    help: str


class FieldEntryOut(Schema):
    name: str
    help: str


class CatalogOut(Schema):
    metrics: list[MetricEntryOut]
    range_functions: dict[str, str]
    aggregations: list[str]
    log_datasets: list[DatasetEntryOut]
    log_fields: list[FieldEntryOut]
    trace_fields: list[FieldEntryOut]
    promql_functions: list[str]
    promql_aggregations: list[str]
    caps: dict[str, int]


class SeriesOut(Schema):
    labels: dict[str, str]
    points: list[tuple[float, float | None]]


class MetricAnswerOut(Schema):
    query_id: str
    series: list[SeriesOut]
    truncated: bool


class LogLineOut(Schema):
    at: str
    level: str
    project_id: str
    server: str
    server_id: str
    service: str
    message: str


class LogAnswerOut(Schema):
    query_id: str
    total: int
    lines: list[LogLineOut]
    truncated: bool
    withheld: int


class SpanOut(Schema):
    trace_id: str
    id: str
    parent_id: str
    name: str
    project_id: str
    service: str
    server: str
    started_at: str
    duration_ms: float
    outcome: str
    attributes: dict[str, str]


class TraceAnswerOut(Schema):
    query_id: str
    spans: list[SpanOut]
    truncated: bool
    withheld: int


class CustomerOut(Schema):
    id: uuid.UUID
    name: str
    keystone_domain_id: str
    tier: CustomerTier
    created_at: datetime
    created_by: str
    updated_at: datetime

    @staticmethod
    def resolve_created_by(customer: Customer) -> str:
        return customer.created_by.username


class DomainOut(Schema):
    id: str
    name: str


class CustomerListingOut(Schema):
    customers: list[CustomerOut]
    unclaimed_domains: list[DomainOut]
    domains_unavailable: bool


class InfraChangeOut(Schema):
    """A change the cloud accepted."""

    change: InfraChange
    target_kind: InfraResource
    target_id: str
    target_name: str
    project_id: str
    ticket: str | None


class CueOut(Schema):
    template: str
    status: CueStatus
    summary: str
    evidence: dict[str, Any]
    link: str | None


class TicketResourceOut(Schema):
    kind: ResourceKind
    resource_id: str
    name: str
    project_id: str
    source: ResourceSource
    token: str | None
    cues: list[CueOut]


class CueRunOut(Schema):
    id: uuid.UUID
    outcome: CueRunOutcome
    started_at: datetime
    finished_at: datetime | None
    started_by: str | None
    window_start: datetime | None
    window_end: datetime | None
    resources: list[TicketResourceOut]
    overview: list[CueOut]

    @staticmethod
    def resolve_started_by(run: CueRun) -> str | None:
        return run.started_by.username if run.started_by else None

    @staticmethod
    def resolve_overview(run: CueRun) -> list[TicketCue]:
        return [cue for cue in run.cues.all() if cue.resource_id is None]


class TicketCuesOut(Schema):
    runs: list[CueRunOut]
