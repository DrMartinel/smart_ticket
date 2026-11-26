"""What a metric, log or trace query answers, parsed from Prometheus's and Elasticsearch's
JSON, and cut to the result cap (F17 FR-F17-007)."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, Self

from apps.infra.domain.catalog import PROJECT_FIELD, PROJECT_LABEL


def value_at(source: dict[str, Any], path: str) -> Any:
    """The value at a dotted `path` of an Elasticsearch document, nested or flat."""
    if path in source:
        return source[path]
    head, _, rest = path.partition(".")
    inner = source.get(head)
    if not rest or not isinstance(inner, dict):
        return None
    return value_at(inner, rest)


def text_at(source: dict[str, Any], path: str) -> str:
    value = value_at(source, path)
    return "" if value is None else str(value)


def number(raw: str) -> float | None:
    """A Prometheus sample value; None for NaN and infinities, which JSON can't carry."""
    value = float(raw)
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class Series:
    """One series of a metric query: its labels and its points as (unix time, value)."""

    labels: dict[str, str]
    points: list[tuple[float, float | None]]

    @classmethod
    def of(cls, raw: dict[str, Any], shown: tuple[str, ...]) -> Series:
        """A series from a range query's matrix, showing only the labels in `shown` and the
        project."""
        labels = {k: v for k, v in raw["metric"].items() if k in shown or k == PROJECT_LABEL}
        return cls(labels, [(float(t), number(v)) for t, v in raw["values"]])

    def free_text(self) -> list[str]:
        return []

    def with_free_text(self, texts: list[str]) -> Self:
        return self


@dataclass(frozen=True)
class LogLine:
    at: str
    level: str
    project_id: str
    server: str
    server_id: str
    service: str
    message: str

    @classmethod
    def of(cls, source: dict[str, Any]) -> LogLine:
        return cls(
            at=text_at(source, "@timestamp"),
            level=text_at(source, "log.level"),
            project_id=text_at(source, PROJECT_FIELD),
            server=text_at(source, "host.name"),
            server_id=text_at(source, "host.id"),
            service=text_at(source, "service.name"),
            message=text_at(source, "message"),
        )

    def free_text(self) -> list[str]:
        return [self.message]

    def with_free_text(self, texts: list[str]) -> Self:
        (message,) = texts
        return replace(self, message=message)


@dataclass(frozen=True)
class Span:
    """A request (a transaction) or a span within one."""

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

    @classmethod
    def of(cls, source: dict[str, Any]) -> Span:
        kind = "transaction" if value_at(source, "transaction.duration.us") is not None else "span"
        labels = value_at(source, "labels") or {}
        project_key = PROJECT_FIELD.removeprefix("labels.")
        return cls(
            trace_id=text_at(source, "trace.id"),
            id=text_at(source, f"{kind}.id"),
            parent_id=text_at(source, "parent.id"),
            name=text_at(source, f"{kind}.name"),
            project_id=text_at(source, PROJECT_FIELD),
            service=text_at(source, "service.name"),
            server=text_at(source, "host.name"),
            started_at=text_at(source, "@timestamp"),
            duration_ms=float(value_at(source, f"{kind}.duration.us") or 0) / 1000,
            outcome=text_at(source, "event.outcome"),
            attributes={k: str(v) for k, v in sorted(labels.items()) if k != project_key},
        )

    def free_text(self) -> list[str]:
        return list(self.attributes.values())

    def with_free_text(self, texts: list[str]) -> Self:
        return replace(self, attributes=dict(zip(self.attributes, texts)))


def hits_of(answer: dict[str, Any]) -> list[dict[str, Any]]:
    """The documents of an Elasticsearch search answer."""
    return [hit["_source"] for hit in answer["hits"]["hits"]]


@dataclass(frozen=True)
class Count:
    """One value of a counted field, and how many lines held it."""

    value: str
    lines: int

    def free_text(self) -> list[str]:
        return []

    def with_free_text(self, texts: list[str]) -> Self:
        return self


def counts_of(answer: dict[str, Any], name: str) -> list[Count]:
    """The buckets of the terms aggregation `name` in an Elasticsearch search answer."""
    return [
        Count(str(b["key"]), int(b["doc_count"])) for b in answer["aggregations"][name]["buckets"]
    ]


def total_of(answer: dict[str, Any]) -> int:
    """How many documents an Elasticsearch search matched."""
    total = answer["hits"]["total"]
    return int(total["value"] if isinstance(total, dict) else total)


def cut_to_bytes[T](items: Sequence[T], cap: int) -> tuple[list[T], bool]:
    """The leading `items` whose JSON fits in `cap` bytes, and whether any were cut."""
    kept: list[T] = []
    used = 2
    for item in items:
        size = len(json.dumps(asdict(item), default=str).encode()) + 1  # type: ignore[call-overload]
        if used + size > cap:
            return kept, True
        kept.append(item)
        used += size
    return kept, False


def unix_time(at: datetime) -> float:
    """`at` as a Prometheus timestamp."""
    return at.astimezone(UTC).timestamp()
