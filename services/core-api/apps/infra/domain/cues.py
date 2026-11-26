"""The fixed cue templates per resource kind and the overview set (F17 §o.6): the structured
query each template sends, and the summary code writes from what it answers, in numbers and
names (BR-F17-16, BR-F17-17, BR-F17-19)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import StrEnum
from typing import Any

from apps.infra.domain.observations import Count, LogLine, Series
from apps.infra.domain.queries import LogCount, LogSearch, MetricQuery, Window
from apps.infra.domain.resources import Alert, Server
from apps.infra.domain.vocabulary import CueStatus, InfraError, InfraRefusal, ResourceKind


class CueTemplate(StrEnum):
    SERVER_STATE = "server.state"
    SERVER_CPU = "server.cpu"
    SERVER_MEMORY = "server.memory"
    SERVER_ERROR_LOGS = "server.error_logs"
    SERVER_ALERTS = "server.alerts"
    VOLUME_READ_LATENCY = "volume.read_latency"
    VOLUME_WRITE_LATENCY = "volume.write_latency"
    VOLUME_IOPS_QUOTA = "volume.iops_quota"
    VOLUME_ALERTS = "volume.alerts"
    NETWORK_DROPPED = "network.dropped_packets"
    NETWORK_ALERTS = "network.alerts"
    OVERVIEW_ALERTS = "overview.alerts"
    OVERVIEW_NOT_RUNNING = "overview.servers_not_running"
    OVERVIEW_ERROR_LOGS = "overview.error_logs"
    OVERVIEW_IOPS_QUOTA = "overview.iops_quota"
    OVERVIEW_CPU = "overview.cpu"


TEMPLATES: dict[ResourceKind, tuple[CueTemplate, ...]] = {
    ResourceKind.SERVER: (
        CueTemplate.SERVER_STATE,
        CueTemplate.SERVER_CPU,
        CueTemplate.SERVER_MEMORY,
        CueTemplate.SERVER_ERROR_LOGS,
        CueTemplate.SERVER_ALERTS,
    ),
    ResourceKind.VOLUME: (
        CueTemplate.VOLUME_READ_LATENCY,
        CueTemplate.VOLUME_WRITE_LATENCY,
        CueTemplate.VOLUME_IOPS_QUOTA,
        CueTemplate.VOLUME_ALERTS,
    ),
    ResourceKind.NETWORK: (CueTemplate.NETWORK_DROPPED, CueTemplate.NETWORK_ALERTS),
}

OVERVIEW = (
    CueTemplate.OVERVIEW_ALERTS,
    CueTemplate.OVERVIEW_NOT_RUNNING,
    CueTemplate.OVERVIEW_ERROR_LOGS,
    CueTemplate.OVERVIEW_IOPS_QUOTA,
    CueTemplate.OVERVIEW_CPU,
)

# Each template's source, as a summary names it, and what its cue is about.
SOURCES: dict[CueTemplate, tuple[str, str]] = {
    CueTemplate.SERVER_STATE: ("the cloud", "state"),
    CueTemplate.SERVER_CPU: ("Prometheus", "CPU"),
    CueTemplate.SERVER_MEMORY: ("Prometheus", "memory"),
    CueTemplate.SERVER_ERROR_LOGS: ("Elasticsearch", "log"),
    CueTemplate.SERVER_ALERTS: ("Alertmanager", "alert"),
    CueTemplate.VOLUME_READ_LATENCY: ("Prometheus", "read latency"),
    CueTemplate.VOLUME_WRITE_LATENCY: ("Prometheus", "write latency"),
    CueTemplate.VOLUME_IOPS_QUOTA: ("Prometheus", "IOPS"),
    CueTemplate.VOLUME_ALERTS: ("Alertmanager", "alert"),
    CueTemplate.NETWORK_DROPPED: ("Prometheus", "dropped packets"),
    CueTemplate.NETWORK_ALERTS: ("Alertmanager", "alert"),
    CueTemplate.OVERVIEW_ALERTS: ("Alertmanager", "alert"),
    CueTemplate.OVERVIEW_NOT_RUNNING: ("the cloud", "server state"),
    CueTemplate.OVERVIEW_ERROR_LOGS: ("Elasticsearch", "log"),
    CueTemplate.OVERVIEW_IOPS_QUOTA: ("Prometheus", "IOPS"),
    CueTemplate.OVERVIEW_CPU: ("Prometheus", "CPU"),
}

_BACKENDS = {
    "prometheus": "Prometheus",
    "elasticsearch": "Elasticsearch",
    "alertmanager": "Alertmanager",
    "cloud": "the cloud",
}

# The label an alert names each kind of resource by.
ALERT_LABEL = {
    ResourceKind.SERVER: "server_id",
    ResourceKind.VOLUME: "volume_id",
    ResourceKind.NETWORK: "network_id",
}

# The log dataset and level the error-log cues read (OQ-F17-07).
LOG_DATASET = "instance"
ERROR_LEVEL = "ERROR"
NOT_RUNNING = ("ERROR", "SHUTOFF")


@dataclass(frozen=True)
class Finding:
    """What one cue says: its status, its summary and its masked evidence."""

    status: CueStatus
    summary: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class Clock:
    """Writes a summary's times in one time zone, with its offset."""

    zone: tzinfo

    def at(self, when: datetime) -> str:
        local = when.astimezone(self.zone)
        offset = local.strftime("%z")
        label = offset[:3] + (f":{offset[3:]}" if offset[3:] != "00" else "")
        return f"{local:%H:%M} ({label})"


@dataclass(frozen=True)
class Peak:
    value: float
    at: datetime
    latest: float


def instant(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def merged(series: list[Series]) -> dict[float, float]:
    """The highest value of `series` at each time."""
    points: dict[float, float] = {}
    for s in series:
        for t, v in s.points:
            if v is not None:
                points[t] = max(points.get(t, v), v)
    return points


def peak_of(points: dict[float, float]) -> Peak | None:
    """The earliest highest point and the last point, None for no points."""
    if not points:
        return None
    at, value = max(points.items(), key=lambda p: (p[1], -p[0]))
    return Peak(value, instant(at), points[max(points)])


def percent(ratio: float) -> str:
    return f"{ratio * 100:.0f} %"


def millis(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


def per_second(rate: float) -> str:
    return f"{rate:.1f}/s"


def started(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def since(text: str, clock: Clock) -> str:
    at = started(text)
    return clock.at(at) if at else text


# ── metric usage ──


@dataclass(frozen=True)
class Usage:
    """A metric a cue shows the peak and latest of, for one resource."""

    label: str
    metric: str
    by: str
    show: Callable[[float], str]
    function: str | None = None
    aggregate: str | None = None

    def query(self, resource_id: str, window: Window, step: int) -> MetricQuery:
        return MetricQuery(
            metric=self.metric,
            window=window,
            step_seconds=step,
            filters={self.by: [resource_id]},
            function=self.function,
            function_seconds=step if self.function else None,
            aggregate=self.aggregate,
        )

    def finding(self, name: str, series: list[Series], clock: Clock) -> Finding:
        found = peak_of(merged(series))
        if found is None:
            return Finding(CueStatus.EMPTY, f"No {self.label.lower()} data for {name}", {})
        return Finding(
            CueStatus.OK,
            f"{self.label} peaked at {self.show(found.value)} at {clock.at(found.at)}, "
            f"now {self.show(found.latest)}",
            {"peak": found.value, "peak_at": found.at.isoformat(), "latest": found.latest},
        )


USAGE = {
    CueTemplate.SERVER_CPU: Usage(
        "CPU", "cloud_server_cpu_utilization_ratio", "server_id", percent
    ),
    CueTemplate.SERVER_MEMORY: Usage(
        "Memory", "cloud_server_memory_used_ratio", "server_id", percent
    ),
    CueTemplate.VOLUME_READ_LATENCY: Usage(
        "Read latency", "cloud_volume_read_latency_seconds", "volume_id", millis
    ),
    CueTemplate.VOLUME_WRITE_LATENCY: Usage(
        "Write latency", "cloud_volume_write_latency_seconds", "volume_id", millis
    ),
    CueTemplate.NETWORK_DROPPED: Usage(
        "Dropped packets",
        "cloud_port_rx_dropped_total",
        "network_id",
        per_second,
        function="rate",
        aggregate="sum",
    ),
}


def cpu_query(window: Window, step: int) -> MetricQuery:
    """Every server's CPU in the scope."""
    return MetricQuery(USAGE[CueTemplate.SERVER_CPU].metric, window, step)


# ── IOPS against quota ──


@dataclass(frozen=True)
class Ratios:
    """A volume's IOPS rate over its quota at each time."""

    volume_id: str
    name: str
    points: dict[float, float]


def iops_queries(
    window: Window, step: int, volume_id: str | None
) -> tuple[MetricQuery, MetricQuery]:
    """The IOPS rate and the IOPS quota of one volume, or of every volume in the scope."""
    filters = {"volume_id": [volume_id]} if volume_id else {}
    rate = MetricQuery(
        "cloud_volume_iops_total",
        window,
        step,
        filters,
        function="rate",
        function_seconds=step,
    )
    return rate, MetricQuery("cloud_volume_iops_quota", window, step, filters)


def iops_ratios(rates: list[Series], quotas: list[Series]) -> list[Ratios]:
    """Each volume's rate divided by its quota at the times both have a value."""
    quota_of = {s.labels.get("volume_id", ""): {t: v for t, v in s.points if v} for s in quotas}
    found = []
    for s in rates:
        volume_id = s.labels.get("volume_id", "")
        quota = quota_of.get(volume_id, {})
        points = {t: v / quota[t] for t, v in s.points if v is not None and t in quota}
        if points:
            found.append(Ratios(volume_id, s.labels.get("volume", volume_id), points))
    return found


def iops_finding(name: str, ratios: list[Ratios], clock: Clock) -> Finding:
    points: dict[float, float] = {}
    for r in ratios:
        for t, v in r.points.items():
            points[t] = max(points.get(t, v), v)
    found = peak_of(points)
    if found is None:
        return Finding(CueStatus.EMPTY, f"No IOPS or quota data for {name}", {})
    full = next((t for t in sorted(points) if round(points[t] * 100) >= 100), None)
    evidence = {
        "peak_ratio": found.value,
        "peak_at": found.at.isoformat(),
        "first_full_at": instant(full).isoformat() if full is not None else None,
        "latest_ratio": found.latest,
    }
    if full is not None:
        summary = (
            f"IOPS reached 100 % of quota at {clock.at(instant(full))}, now {percent(found.latest)}"
        )
    else:
        summary = (
            f"IOPS peaked at {percent(found.value)} of quota at {clock.at(found.at)}, "
            f"now {percent(found.latest)}"
        )
    return Finding(CueStatus.OK, summary, evidence)


# ── logs ──


def error_lines(server_id: str, window: Window, size: int) -> LogSearch:
    """One server's error lines, newest first."""
    return LogSearch(
        window=window,
        dataset=LOG_DATASET,
        filters={"server_id": [server_id], "level": [ERROR_LEVEL]},
        size=size,
    )


def error_counts(window: Window, size: int) -> LogCount:
    """The servers with the most error lines in the scope."""
    return LogCount(
        window=window, dataset=LOG_DATASET, by="server", size=size, filters={"level": [ERROR_LEVEL]}
    )


def log_finding(name: str, total: int, lines: list[LogLine]) -> Finding:
    if total == 0:
        return Finding(CueStatus.EMPTY, f"No error lines in {name}'s logs", {"total": 0})
    return Finding(
        CueStatus.OK,
        f"{total} error line{'s' if total != 1 else ''} in {name}'s logs",
        {"total": total, "lines": [{"at": line.at, "message": line.message} for line in lines]},
    )


# ── alerts and state ──


def about(alerts: list[Alert], kind: ResourceKind, resource_id: str) -> list[Alert]:
    """The alerts whose labels name the resource."""
    return [a for a in alerts if a.labels.get(ALERT_LABEL[kind]) == resource_id]


def alert_row(alert: Alert) -> dict[str, Any]:
    return {
        "name": alert.name,
        "severity": alert.severity,
        "state": alert.state,
        "starts_at": alert.starts_at,
        "summary": alert.summary,
    }


def alerts_finding(name: str, alerts: list[Alert], clock: Clock) -> Finding:
    if not alerts:
        return Finding(CueStatus.EMPTY, f"No alerts firing on {name}", {"alerts": []})
    ordered = sorted(alerts, key=lambda a: a.starts_at)
    return Finding(
        CueStatus.OK,
        "; ".join(f"{a.name} firing since {since(a.starts_at, clock)}" for a in ordered),
        {"alerts": [alert_row(a) for a in ordered]},
    )


def state_finding(server: Server, now: datetime) -> Finding:
    state = server.status + (f" ({server.task_state})" if server.task_state else "")
    changed = started(server.updated)
    if changed is None:
        summary = state
    else:
        minutes = max(0, int((now - changed).total_seconds() // 60))
        summary = f"{state}, last changed {minutes} min ago"
    return Finding(
        CueStatus.OK,
        summary,
        {"status": server.status, "task_state": server.task_state, "updated": server.updated},
    )


# ── the overview ──


def linkable(kind: ResourceKind, resource_id: str | None, name: str) -> dict[str, Any]:
    """An overview row's resource, which a person may link when its ID is known."""
    return {"kind": kind.value, "resource_id": resource_id, "resource": name}


def alert_subject(alert: Alert) -> dict[str, Any]:
    """The volume, server or network an alert's labels name, in that order."""
    for kind in (ResourceKind.VOLUME, ResourceKind.SERVER, ResourceKind.NETWORK):
        resource_id = alert.labels.get(ALERT_LABEL[kind])
        if resource_id:
            return linkable(kind, resource_id, alert.labels.get(kind.value, resource_id))
    return {"resource": "its project"}


def overview_alerts(alerts: list[Alert], top: int, clock: Clock) -> Finding:
    if not alerts:
        return Finding(CueStatus.EMPTY, "No alerts firing in these projects", {"alerts": []})
    rows = [
        {**alert_row(a), **alert_subject(a)}
        for a in sorted(alerts, key=lambda a: a.starts_at)[:top]
    ]
    count = f"{len(alerts)} alert{'s' if len(alerts) != 1 else ''} firing: "
    return Finding(
        CueStatus.OK,
        count
        + "; ".join(
            f"{r['name']} firing on {r['resource']} since {since(r['starts_at'], clock)}"
            for r in rows
        ),
        {"alerts": rows},
    )


def not_running(servers: list[Server], top: int, clock: Clock) -> Finding:
    stopped = sorted(
        (s for s in servers if s.status in NOT_RUNNING), key=lambda s: (s.updated, s.name)
    )[:top]
    if not stopped:
        return Finding(CueStatus.EMPTY, "No server in ERROR or SHUTOFF", {"servers": []})
    return Finding(
        CueStatus.OK,
        "; ".join(f"{s.name} {s.status} since {since(s.updated, clock)}" for s in stopped),
        {
            "servers": [
                {
                    **linkable(ResourceKind.SERVER, s.id, s.name),
                    "status": s.status,
                    "since": s.updated,
                }
                for s in stopped
            ]
        },
    )


def most_errors(counts: list[Count], server_ids: dict[str, str]) -> Finding:
    if not counts:
        return Finding(CueStatus.EMPTY, "No error lines in these projects", {"servers": []})
    return Finding(
        CueStatus.OK,
        "Most error lines: " + ", ".join(f"{c.value} {c.lines}" for c in counts),
        {
            "servers": [
                {
                    **linkable(ResourceKind.SERVER, server_ids.get(c.value), c.value),
                    "lines": c.lines,
                }
                for c in counts
            ]
        },
    )


def nearest_quota(ratios: list[Ratios], top: int) -> Finding:
    peaks = sorted(((r, max(r.points.values())) for r in ratios), key=lambda p: (-p[1], p[0].name))[
        :top
    ]
    if not peaks:
        return Finding(CueStatus.EMPTY, "No IOPS or quota data in these projects", {"volumes": []})
    return Finding(
        CueStatus.OK,
        "Nearest their IOPS quota: " + ", ".join(f"{r.name} {percent(p)}" for r, p in peaks),
        {
            "volumes": [
                {**linkable(ResourceKind.VOLUME, r.volume_id, r.name), "peak_ratio": p}
                for r, p in peaks
            ]
        },
    )


def highest_cpu(series: list[Series], top: int) -> Finding:
    peaks = sorted(
        (
            (s.labels.get("server", ""), s.labels.get("server_id", ""), found.value)
            for s in series
            if (found := peak_of(merged([s]))) is not None
        ),
        key=lambda p: (-p[2], p[0]),
    )[:top]
    if not peaks:
        return Finding(CueStatus.EMPTY, "No CPU data in these projects", {"servers": []})
    return Finding(
        CueStatus.OK,
        "Highest CPU: " + ", ".join(f"{name} {percent(value)}" for name, _, value in peaks),
        {
            "servers": [
                {**linkable(ResourceKind.SERVER, server_id, name), "peak": value}
                for name, server_id, value in peaks
            ]
        },
    )


# ── a cue whose read failed ──


def failed(template: CueTemplate, error: InfraError) -> Finding:
    """The cue a refused, missing or unreachable read leaves, naming its source and reason."""
    source, noun = SOURCES[template]
    details = error.details if isinstance(error.details, dict) else {}
    if error.code is InfraRefusal.QUERY_REFUSED:
        check = str(details.get("reason", ""))
        return Finding(
            CueStatus.REFUSED,
            f"{source[0].upper()}{source[1:]} {noun} query refused ({check}): {error.message}",
            {"check": check},
        )
    if error.code is InfraRefusal.NOT_FOUND:
        return Finding(
            CueStatus.EMPTY, f"{source[0].upper()}{source[1:]} has no such resource now", {}
        )
    backend = _BACKENDS.get(str(details.get("backend", "")), source)
    return Finding(
        CueStatus.UNAVAILABLE,
        f"{backend[0].upper()}{backend[1:]} was unreachable; no {noun} cue",
        {"backend": backend},
    )
