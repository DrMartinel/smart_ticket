"""What a structured query may name (F17 FR-F17-003, ADR-0048 §4): the cloud's metrics and
their labels, the range functions and aggregations, the log datasets and the log and trace
fields, each for staff or for customers too (OQ-F17-07)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from apps.infra.domain.vocabulary import QueryCheck, QueryRefused

if TYPE_CHECKING:
    from config.settings.base import InfraThresholds


class Surface(StrEnum):
    STAFF = "staff"
    CUSTOMER = "customer"


class MetricKind(StrEnum):
    GAUGE = "gauge"
    COUNTER = "counter"


# The label every cloud series carries its project in; core-api sets it, a query never names it.
PROJECT_LABEL = "project"
# The field every log line and span carries its project in, as the APM Server indexes cloud-sim's
# `openstack.project_id` resource attribute.
PROJECT_FIELD = "labels.openstack_project_id"
# The field a log line's or span's time is in.
TIME_FIELD = "@timestamp"
# The field a log line's text is in.
MESSAGE_FIELD = "message"

_SERVER = (PROJECT_LABEL, "project_name", "server_id", "server", "host")
_VOLUME = (PROJECT_LABEL, "project_name", "volume_id", "volume", "server_id")
_PORT = (PROJECT_LABEL, "project_name", "port_id", "network_id", "server_id", "server")
# Labels naming the provider's own machines: the hypervisor a server runs on.
_STAFF_ONLY_LABELS = frozenset({"host"})


@dataclass(frozen=True)
class Metric:
    name: str
    kind: MetricKind
    help: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Field:
    """A log or trace field a query names, and where Elasticsearch holds it."""

    name: str
    path: str
    help: str


@dataclass(frozen=True)
class Dataset:
    """A set of log data streams a log search may read."""

    name: str
    index: str
    help: str
    staff_only: bool


METRICS = (
    Metric("cloud_server_up", MetricKind.GAUGE, "1 if the server's guest answers", _SERVER),
    Metric(
        "cloud_server_status",
        MetricKind.GAUGE,
        "1 for the server's current Nova status",
        (*_SERVER, "status"),
    ),
    Metric("cloud_server_cpu_utilization_ratio", MetricKind.GAUGE, "CPU in use, 0 to 1", _SERVER),
    Metric("cloud_server_memory_used_ratio", MetricKind.GAUGE, "Memory in use, 0 to 1", _SERVER),
    Metric("cloud_server_disk_used_ratio", MetricKind.GAUGE, "Root disk in use, 0 to 1", _SERVER),
    Metric("cloud_volume_read_latency_seconds", MetricKind.GAUGE, "Mean read latency", _VOLUME),
    Metric("cloud_volume_write_latency_seconds", MetricKind.GAUGE, "Mean write latency", _VOLUME),
    Metric("cloud_volume_iops_total", MetricKind.COUNTER, "I/O operations served", _VOLUME),
    Metric("cloud_volume_iops_quota", MetricKind.GAUGE, "The volume's IOPS limit", _VOLUME),
    Metric("cloud_port_rx_packets_total", MetricKind.COUNTER, "Packets received", _PORT),
    Metric("cloud_port_tx_packets_total", MetricKind.COUNTER, "Packets sent", _PORT),
    Metric("cloud_port_rx_dropped_total", MetricKind.COUNTER, "Packets dropped", _PORT),
)

# The range functions a structured metric query may apply, and the kind of metric each takes.
RANGE_FUNCTIONS = {
    "rate": MetricKind.COUNTER,
    "increase": MetricKind.COUNTER,
    "avg_over_time": MetricKind.GAUGE,
    "min_over_time": MetricKind.GAUGE,
    "max_over_time": MetricKind.GAUGE,
}
AGGREGATIONS = ("avg", "sum", "min", "max", "count")

LOG_DATASETS = (
    Dataset("instance", "logs-apm.app*", "What the workloads on the servers log", False),
    Dataset("apm_errors", "logs-apm.error*", "Errors the APM agents report", True),
)
LOG_FIELDS = (
    Field("server", "host.name", "The server's name"),
    Field("server_id", "host.id", "The server's id"),
    Field("service", "service.name", "The workload on the server"),
    Field("level", "log.level", "INFO, WARN or ERROR"),
)
# Spans are searched by their root (a transaction, in Elastic APM's terms).
TRACE_INDEX = "traces-apm*"
TRACE_FIELDS = (
    Field("server", "host.name", "The server's name"),
    Field("server_id", "host.id", "The server's id"),
    Field("service", "service.name", "The workload on the server"),
    Field("name", "transaction.name", "The request's name"),
    Field("outcome", "event.outcome", "success or failure"),
)


@dataclass(frozen=True)
class MetricEntry:
    name: str
    kind: str
    help: str
    labels: list[str]


@dataclass(frozen=True)
class DatasetEntry:
    name: str
    help: str


@dataclass(frozen=True)
class FieldEntry:
    name: str
    help: str


@dataclass(frozen=True)
class Listing:
    """The catalog as a query's author reads it, with the caps a query must stay within."""

    metrics: list[MetricEntry]
    range_functions: dict[str, str]
    aggregations: list[str]
    log_datasets: list[DatasetEntry]
    log_fields: list[FieldEntry]
    trace_fields: list[FieldEntry]
    caps: dict[str, int]


@dataclass(frozen=True)
class Catalog:
    """What one surface's queries may name."""

    surface: Surface

    @property
    def metrics(self) -> tuple[Metric, ...]:
        return METRICS

    @property
    def datasets(self) -> tuple[Dataset, ...]:
        return tuple(d for d in LOG_DATASETS if self.surface is Surface.STAFF or not d.staff_only)

    def metric(self, name: str) -> Metric:
        """The metric named `name`; refuses one the catalog doesn't list."""
        found = next((m for m in METRICS if m.name == name), None)
        if found is None:
            raise QueryRefused(QueryCheck.DATASET, f"no metric {name!r}; see the catalog")
        return found

    def labels_of(self, metric: Metric) -> tuple[str, ...]:
        """The labels a query may filter or group `metric` by, and an answer shows."""
        return tuple(
            label
            for label in metric.labels
            if label != PROJECT_LABEL
            and (self.surface is Surface.STAFF or label not in _STAFF_ONLY_LABELS)
        )

    def label(self, metric: Metric, name: str) -> str:
        """`name` if a query may name it on `metric`; refuses any other label."""
        if name not in self.labels_of(metric):
            raise QueryRefused(QueryCheck.FIELD, f"{metric.name} has no label {name!r}")
        return name

    def dataset(self, name: str) -> Dataset:
        """The log dataset named `name`; refuses one this surface may not read."""
        found = next((d for d in self.datasets if d.name == name), None)
        if found is None:
            raise QueryRefused(QueryCheck.DATASET, f"no log dataset {name!r}; see the catalog")
        return found

    @staticmethod
    def field(fields: tuple[Field, ...], name: str) -> Field:
        """The field named `name` in `fields`; refuses any other."""
        found = next((f for f in fields if f.name == name), None)
        if found is None:
            raise QueryRefused(QueryCheck.FIELD, f"no field {name!r}; see the catalog")
        return found

    def listing(self, caps: InfraThresholds) -> Listing:
        return Listing(
            metrics=[
                MetricEntry(m.name, m.kind.value, m.help, list(self.labels_of(m)))
                for m in self.metrics
            ],
            range_functions={name: kind.value for name, kind in RANGE_FUNCTIONS.items()},
            aggregations=list(AGGREGATIONS),
            log_datasets=[DatasetEntry(d.name, d.help) for d in self.datasets],
            log_fields=[FieldEntry(f.name, f.help) for f in LOG_FIELDS],
            trace_fields=[FieldEntry(f.name, f.help) for f in TRACE_FIELDS],
            caps=caps.model_dump(),
        )
