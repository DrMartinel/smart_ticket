"""Structured queries of the cloud's metrics, logs and traces, checked against the catalog and
the caps and compiled to PromQL or Elasticsearch DSL with the caller's projects in every
filter (F17 FR-F17-004, FR-F17-006, BR-F17-05). No other code builds Elasticsearch DSL."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from apps.infra.domain.catalog import (
    AGGREGATIONS,
    LOG_FIELDS,
    MESSAGE_FIELD,
    PROJECT_FIELD,
    PROJECT_LABEL,
    RANGE_FUNCTIONS,
    TIME_FIELD,
    TRACE_FIELDS,
    TRACE_INDEX,
    Catalog,
    MetricKind,
)
from apps.infra.domain.vocabulary import QueryCheck, QueryRefused

if TYPE_CHECKING:
    from config.settings.base import InfraThresholds

Filters = dict[str, list[str]]

_RE2_SPECIAL = frozenset("\\.+*?()|[]{}^$")


def promql_string(value: str) -> str:
    """`value` as a double-quoted PromQL string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def regex_literal(value: str) -> str:
    """A regular expression matching exactly `value`."""
    return "".join(f"\\{c}" if c in _RE2_SPECIAL else c for c in value)


def matcher(label: str, values: list[str]) -> str:
    """A PromQL matcher: `label` equal to the one value, or to any of several."""
    if len(values) == 1:
        return f"{label}={promql_string(values[0])}"
    return f"{label}=~{promql_string('|'.join(regex_literal(v) for v in sorted(values)))}"


def kql_values(path: str, values: list[str]) -> str:
    """A KQL clause: `path` equal to any of `values`."""
    quoted = " or ".join('"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values)
    return f"{path}:({quoted})"


def rison(value: str) -> str:
    """`value` as a quoted Rison string, for a Kibana link."""
    return "'" + value.replace("!", "!!").replace("'", "!'") + "'"


@dataclass(frozen=True)
class Window:
    """A query's time range."""

    start: datetime
    end: datetime

    def check(self, caps: InfraThresholds) -> None:
        """Refuses a range that ends before it starts or is longer than the cap."""
        if self.end <= self.start:
            raise QueryRefused(QueryCheck.RANGE, "end must be after start")
        if (self.end - self.start).total_seconds() > caps.max_range_hours * 3600:
            raise QueryRefused(
                QueryCheck.RANGE, f"the range is over {caps.max_range_hours} hours; narrow it"
            )

    def seconds(self) -> int:
        return int((self.end - self.start).total_seconds())

    def graph_link(self, base: str, promql: str, step_seconds: int) -> str:
        """`promql` over this range in Prometheus's own graph page."""
        params = {
            "g0.expr": promql,
            "g0.tab": "0",
            "g0.range_input": f"{self.seconds()}s",
            "g0.end_input": self.end.strftime("%Y-%m-%d %H:%M:%S"),
            "g0.step_input": str(step_seconds),
        }
        return f"{base}/graph?{urlencode(params)}"


def checked_filters(filters: Filters) -> None:
    """Refuses a filter with no value."""
    for name, values in filters.items():
        if not values:
            raise QueryRefused(QueryCheck.FIELD, f"the filter on {name!r} has no value")


def checked_size(size: int | None, cap: int) -> int:
    """`size`, or the cap when none is given; refuses one over the cap."""
    if size is None:
        return cap
    if size > cap:
        raise QueryRefused(QueryCheck.SIZE, f"at most {cap} at once; narrow the query")
    return size


@dataclass(frozen=True)
class MetricQuery:
    """A metric over a range: filtered on its labels, optionally through a range function and
    an aggregation."""

    metric: str
    window: Window
    step_seconds: int
    filters: Filters = field(default_factory=dict)
    function: str | None = None
    function_seconds: int | None = None
    aggregate: str | None = None
    by: list[str] = field(default_factory=list)

    def promql(self, catalog: Catalog, caps: InfraThresholds, projects: frozenset[str]) -> str:
        """The PromQL for this query, scoped to `projects`; refuses a query that names what the
        catalog doesn't list or goes over a cap."""
        if not projects:
            raise ValueError("a metric query needs at least one project")
        metric = catalog.metric(self.metric)
        self.window.check(caps)
        if self.step_seconds < caps.min_step_seconds:
            raise QueryRefused(QueryCheck.STEP, f"the step is under {caps.min_step_seconds} s")
        checked_filters(self.filters)
        matchers = [matcher(PROJECT_LABEL, sorted(projects))] + [
            matcher(catalog.label(metric, name), values)
            for name, values in sorted(self.filters.items())
        ]
        expr = f"{metric.name}{{{','.join(matchers)}}}"
        if self.function is not None:
            if RANGE_FUNCTIONS.get(self.function) is not metric.kind:
                raise QueryRefused(
                    QueryCheck.FUNCTION,
                    f"{self.function!r} doesn't apply to the {metric.kind.value} {metric.name}",
                )
            if self.function_seconds is None or self.function_seconds < caps.min_step_seconds:
                raise QueryRefused(
                    QueryCheck.STEP,
                    f"{self.function} needs function_seconds of at least {caps.min_step_seconds}",
                )
            if self.function_seconds > caps.max_range_hours * 3600:
                raise QueryRefused(QueryCheck.RANGE, f"{self.function}'s range is over the cap")
            expr = f"{self.function}({expr}[{self.function_seconds}s])"
        elif metric.kind is MetricKind.COUNTER:
            raise QueryRefused(
                QueryCheck.FUNCTION, f"{metric.name} is a counter: apply rate or increase"
            )
        if self.aggregate is not None:
            if self.aggregate not in AGGREGATIONS:
                raise QueryRefused(QueryCheck.FUNCTION, f"no aggregation {self.aggregate!r}")
            by = ", ".join(catalog.label(metric, label) for label in self.by)
            expr = f"{self.aggregate} by ({by}) ({expr})" if by else f"{self.aggregate} ({expr})"
        elif self.by:
            raise QueryRefused(QueryCheck.FUNCTION, "grouping by labels needs an aggregate")
        return expr

    def link(self, base: str, promql: str) -> str:
        """The query in Prometheus's own graph page."""
        return self.window.graph_link(base, promql, self.step_seconds)


@dataclass(frozen=True)
class Search:
    """An Elasticsearch search: the indices it reads, its body and the KQL a person can run."""

    index: str
    body: dict[str, Any]
    kql: str
    window: Window | None

    def compiled(self) -> str:
        """The search as an `infra_queries.compiled` value."""
        return f"POST /{self.index}/_search\n{json.dumps(self.body, sort_keys=True)}"

    def discover_link(self, base: str) -> str:
        """The search in Kibana's Discover."""
        time = (
            f"(time:(from:{rison(self.window.start.isoformat())},"
            f"to:{rison(self.window.end.isoformat())}))"
            if self.window
            else "()"
        )
        query = f"(query:(language:kuery,query:{rison(self.kql)}))"
        safe = "():,'!"
        return f"{base}/app/discover#/?_g={quote(time, safe=safe)}&_a={quote(query, safe=safe)}"


def scoped(projects: frozenset[str], window: Window | None) -> list[dict[str, Any]]:
    """The filters every search carries: the caller's projects, and its time range."""
    if not projects:
        raise ValueError("a search needs at least one project")
    filters: list[dict[str, Any]] = [{"terms": {PROJECT_FIELD: sorted(projects)}}]
    if window is not None:
        filters.append(
            {
                "range": {
                    TIME_FIELD: {"gte": window.start.isoformat(), "lte": window.end.isoformat()}
                }
            }
        )
    return filters


def kql_scoped(projects: frozenset[str]) -> list[str]:
    return [kql_values(PROJECT_FIELD, sorted(projects))]


@dataclass(frozen=True)
class LogSearch:
    """Log lines of one dataset in a range, filtered on fields and optionally matching text."""

    window: Window
    dataset: str
    text: str | None = None
    filters: Filters = field(default_factory=dict)
    size: int | None = None

    def search(self, catalog: Catalog, caps: InfraThresholds, projects: frozenset[str]) -> Search:
        """The Elasticsearch search for this query, scoped to `projects`."""
        dataset = catalog.dataset(self.dataset)
        self.window.check(caps)
        checked_filters(self.filters)
        size = checked_size(self.size, caps.max_log_docs)
        filters, kql = scoped(projects, self.window), kql_scoped(projects)
        for name, values in sorted(self.filters.items()):
            path = catalog.field(LOG_FIELDS, name).path
            filters.append({"terms": {path: values}})
            kql.append(kql_values(path, values))
        query: dict[str, Any] = {"filter": filters}
        if self.text:
            query["must"] = [{"match": {MESSAGE_FIELD: {"query": self.text, "operator": "and"}}}]
            kql.append(kql_values(MESSAGE_FIELD, [self.text]))
        body = {
            "size": size,
            "sort": [{TIME_FIELD: {"order": "desc"}}],
            "track_total_hits": True,
            "query": {"bool": query},
        }
        return Search(dataset.index, body, " and ".join(kql), self.window)


@dataclass(frozen=True)
class TraceSearch:
    """Requests (root spans) in a range, filtered on fields and a shortest duration."""

    window: Window
    filters: Filters = field(default_factory=dict)
    min_duration_ms: int | None = None
    size: int | None = None

    def search(self, catalog: Catalog, caps: InfraThresholds, projects: frozenset[str]) -> Search:
        """The Elasticsearch search for this query, scoped to `projects`."""
        self.window.check(caps)
        checked_filters(self.filters)
        size = checked_size(self.size, caps.max_spans)
        filters = [*scoped(projects, self.window), {"term": {"processor.event": "transaction"}}]
        kql = [*kql_scoped(projects), 'processor.event:"transaction"']
        for name, values in sorted(self.filters.items()):
            path = catalog.field(TRACE_FIELDS, name).path
            filters.append({"terms": {path: values}})
            kql.append(kql_values(path, values))
        if self.min_duration_ms is not None:
            micros = self.min_duration_ms * 1000
            filters.append({"range": {"transaction.duration.us": {"gte": micros}}})
            kql.append(f"transaction.duration.us >= {micros}")
        body = {
            "size": size,
            "sort": [{TIME_FIELD: {"order": "desc"}}],
            "query": {"bool": {"filter": filters}},
        }
        return Search(TRACE_INDEX, body, " and ".join(kql), self.window)


def trace_search(trace_id: str, caps: InfraThresholds, projects: frozenset[str]) -> Search:
    """Every span of one trace within `projects`, oldest first."""
    filters = [*scoped(projects, None), {"term": {"trace.id": trace_id}}]
    body = {
        "size": caps.max_spans,
        "sort": [{TIME_FIELD: {"order": "asc"}}],
        "query": {"bool": {"filter": filters}},
    }
    kql = " and ".join([*kql_scoped(projects), kql_values("trace.id", [trace_id])])
    return Search(TRACE_INDEX, body, kql, None)
