"""A caller's queries of the cloud's metrics, logs and traces (F17 §h.1): compiled, or for raw
PromQL parsed and written back out, with their projects in every filter, cut to the result cap,
free text masked, and each recorded as one `infra_queries` row with a link a person can open
(BR-F17-05..07, BR-F17-10, FR-F17-005)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.accounts.permissions import Caller
from apps.infra.clients.backends import (
    BackendNotFound,
    Elasticsearch,
    OpenStack,
    Prometheus,
    elasticsearch,
    openstack,
    prometheus,
)
from apps.infra.domain.catalog import Catalog, Surface
from apps.infra.domain.observations import (
    Count,
    LogLine,
    Series,
    Span,
    counts_of,
    cut_to_bytes,
    hits_of,
    total_of,
    unix_time,
)
from apps.infra.domain.promql import PromQLQuery
from apps.infra.domain.queries import (
    COUNTS,
    LogCount,
    LogSearch,
    MetricQuery,
    Search,
    TraceSearch,
    trace_search,
)
from apps.infra.domain.vocabulary import QueryCheck, QueryRefused
from apps.infra.models import InfraBackend, InfraQueryKind
from apps.infra.services.recording import QueryLog, Read
from apps.infra.services.scope import InfraScope


@dataclass(frozen=True)
class MetricAnswer:
    query_id: str
    series: list[Series]
    truncated: bool


@dataclass(frozen=True)
class LogAnswer:
    query_id: str
    total: int
    lines: list[LogLine]
    truncated: bool
    withheld: int


@dataclass(frozen=True)
class CountAnswer:
    query_id: str
    total: int
    counts: list[Count]


@dataclass(frozen=True)
class TraceAnswer:
    query_id: str
    spans: list[Span]
    truncated: bool
    withheld: int


class Observability:
    """The cloud's metrics, logs and traces, as one caller may see them."""

    def __init__(
        self,
        log: QueryLog,
        scope: InfraScope,
        catalog: Catalog,
        cloud: OpenStack,
        prometheus: Prometheus,
        elasticsearch: Elasticsearch,
    ) -> None:
        self.log = log
        self.scope = scope
        self.catalog = catalog
        self.cloud = cloud
        self.prometheus = prometheus
        self.elasticsearch = elasticsearch
        self.caps = settings.THRESHOLDS.infra

    @classmethod
    def for_all(cls, caller: Caller) -> Observability:
        """Staff queries across every cloud project."""
        return cls(
            QueryLog.of(caller),
            InfraScope.all(),
            Catalog(Surface.STAFF),
            openstack(),
            prometheus(),
            elasticsearch(),
        )

    @classmethod
    def for_own(cls, caller: Caller) -> Observability:
        """Customer queries narrowed to the caller's Keystone projects."""
        log, cloud = QueryLog.of(caller), openstack()
        return cls(
            log,
            log.own_scope(cloud),
            Catalog(Surface.CUSTOMER),
            cloud,
            prometheus(),
            elasticsearch(),
        )

    # ── metrics ──

    def metrics(self, query: MetricQuery, project_id: str | None) -> MetricAnswer:
        wanted = self.scope.narrowed_to(project_id)
        with self.log.read(InfraBackend.PROMETHEUS, InfraQueryKind.STRUCTURED, wanted) as read:
            projects = self.covered(wanted)
            series: list[Series] = []
            truncated = False
            if projects:
                promql = query.promql(self.catalog, self.caps, projects)
                read.calls.append(promql)
                read.link = query.link(settings.PROMETHEUS_UI_URL, promql)
                found = self.matrix(query, promql, projects)
                shown = self.catalog.labels_of(self.catalog.metric(query.metric))
                series, truncated = cut_to_bytes(
                    [Series.of(s, shown) for s in found], self.caps.max_result_bytes
                )
            series = read.shown(series)
        return MetricAnswer(str(read.query_id), series, truncated)

    def promql(self, query: PromQLQuery, project_id: str | None) -> MetricAnswer:
        """Raw PromQL, run only as Prometheus parsed it and core-api checked and scoped it."""
        wanted = self.scope.narrowed_to(project_id)
        with self.log.read(InfraBackend.PROMETHEUS, InfraQueryKind.PROMQL, wanted) as read:
            read.calls.append(query.text)
            query.check(self.caps)
            projects = self.covered(wanted)
            series: list[Series] = []
            truncated = False
            if projects:
                try:
                    promql = query.scoped(self.prometheus.parse(query.text), self.caps, projects)
                except RecursionError as e:
                    raise QueryRefused(
                        QueryCheck.UNSUPPORTED, "the query nests too deeply; split it"
                    ) from e
                read.calls[-1] = promql
                read.link = query.link(settings.PROMETHEUS_UI_URL, promql)
                found = self.matrix(query, promql, projects)
                series, truncated = cut_to_bytes(
                    [Series.of(s, tuple(s["metric"])) for s in found], self.caps.max_result_bytes
                )
            series = read.shown(series)
        return MetricAnswer(str(read.query_id), series, truncated)

    # ── logs ──

    def logs(self, query: LogSearch, project_id: str | None) -> LogAnswer:
        wanted = self.scope.narrowed_to(project_id)
        with self.log.read(InfraBackend.ELASTICSEARCH, InfraQueryKind.STRUCTURED, wanted) as read:
            projects = self.covered(wanted)
            lines: list[LogLine] = []
            total, truncated = 0, False
            if projects:
                answer = self.search(read, query.search(self.catalog, self.caps, projects))
                total = total_of(answer)
                lines, truncated = cut_to_bytes(
                    [LogLine.of(h) for h in hits_of(answer)], self.caps.max_result_bytes
                )
            lines = read.shown(lines)
        return LogAnswer(str(read.query_id), total, lines, truncated, read.withheld)

    def log_counts(self, query: LogCount, project_id: str | None) -> CountAnswer:
        wanted = self.scope.narrowed_to(project_id)
        with self.log.read(InfraBackend.ELASTICSEARCH, InfraQueryKind.STRUCTURED, wanted) as read:
            projects = self.covered(wanted)
            counts: list[Count] = []
            total = 0
            if projects:
                answer = self.search(read, query.search(self.catalog, self.caps, projects))
                total, counts = total_of(answer), counts_of(answer, COUNTS)
            counts = read.shown(counts)
        return CountAnswer(str(read.query_id), total, counts)

    # ── traces ──

    def traces(self, query: TraceSearch, project_id: str | None) -> TraceAnswer:
        wanted = self.scope.narrowed_to(project_id)
        with self.log.read(InfraBackend.ELASTICSEARCH, InfraQueryKind.STRUCTURED, wanted) as read:
            projects = self.covered(wanted)
            spans: list[Span] = []
            truncated = False
            if projects:
                answer = self.search(read, query.search(self.catalog, self.caps, projects))
                spans, truncated = cut_to_bytes(
                    [Span.of(h) for h in hits_of(answer)], self.caps.max_result_bytes
                )
            spans = read.shown(spans)
        return TraceAnswer(str(read.query_id), spans, truncated, read.withheld)

    def trace(self, trace_id: str) -> TraceAnswer:
        """Every span of one trace; a trace outside the scope is not found, like a missing one."""
        wanted = self.scope.narrowed_to(None)
        with self.log.read(InfraBackend.ELASTICSEARCH, InfraQueryKind.STRUCTURED, wanted) as read:
            projects = self.covered(wanted)
            if not projects:
                raise BackendNotFound(f"trace {trace_id}")
            answer = self.search(read, trace_search(trace_id, self.caps, projects))
            read.link = f"{settings.KIBANA_URL}/app/apm/link-to/trace/{trace_id}"
            found = hits_of(answer)
            if not found:
                raise BackendNotFound(f"trace {trace_id}")
            spans, truncated = cut_to_bytes([Span.of(h) for h in found], self.caps.max_result_bytes)
            spans = read.shown(spans)
        return TraceAnswer(str(read.query_id), spans, truncated, read.withheld)

    # ── how a query runs ──

    def covered(self, wanted: frozenset[str] | None) -> frozenset[str]:
        """The projects a query is scoped to: `wanted`, or every project Keystone lists."""
        if wanted is not None:
            return wanted
        found = self.cloud.get("identity", "/projects")["projects"]
        return frozenset(p["id"] for p in found)

    def matrix(
        self, query: MetricQuery | PromQLQuery, promql: str, projects: frozenset[str]
    ) -> Any:
        """The series `promql` answers over the query's range; refuses more than the cap."""
        found = self.prometheus.query_range(
            promql,
            unix_time(query.window.start),
            unix_time(query.window.end),
            query.step_seconds,
            projects,
        )
        if len(found) > self.caps.max_series:
            raise QueryRefused(
                QueryCheck.SERIES,
                f"{len(found)} series, over {self.caps.max_series}; filter or aggregate",
            )
        return found

    def search(self, read: Read, search: Search) -> Any:
        """Sends `search` to Elasticsearch, named in the read's record."""
        read.calls.append(search.compiled())
        read.link = search.discover_link(settings.KIBANA_URL)
        return self.elasticsearch.search(search.index, search.body)
