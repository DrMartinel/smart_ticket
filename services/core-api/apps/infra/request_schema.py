"""Request shapes for the infra queries (F17 §h.1), whose catalog and caps are checked when the
query compiles, and the customer routes' bodies (F17 §o.9)."""

from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema
from pydantic import ConfigDict

from apps.infra.domain.queries import LogSearch, MetricQuery, TraceSearch, Window
from apps.infra.models import CustomerTier


class MetricQueryIn(Schema):
    metric: str
    start: datetime
    end: datetime
    step_seconds: int = Field(ge=1)
    filters: dict[str, list[str]] = {}
    function: str | None = None
    function_seconds: int | None = Field(default=None, ge=1)
    aggregate: str | None = None
    by: list[str] = []
    project_id: str | None = None

    def query(self) -> MetricQuery:
        return MetricQuery(
            metric=self.metric,
            window=Window(self.start, self.end),
            step_seconds=self.step_seconds,
            filters=self.filters,
            function=self.function,
            function_seconds=self.function_seconds,
            aggregate=self.aggregate,
            by=self.by,
        )


class LogSearchIn(Schema):
    start: datetime
    end: datetime
    dataset: str = "instance"
    text: str | None = Field(default=None, max_length=500)
    filters: dict[str, list[str]] = {}
    size: int | None = Field(default=None, ge=1)
    project_id: str | None = None

    def query(self) -> LogSearch:
        return LogSearch(
            window=Window(self.start, self.end),
            dataset=self.dataset,
            text=self.text,
            filters=self.filters,
            size=self.size,
        )


class TraceSearchIn(Schema):
    start: datetime
    end: datetime
    filters: dict[str, list[str]] = {}
    min_duration_ms: int | None = Field(default=None, ge=0)
    size: int | None = Field(default=None, ge=1)
    project_id: str | None = None

    def query(self) -> TraceSearch:
        return TraceSearch(
            window=Window(self.start, self.end),
            filters=self.filters,
            min_duration_ms=self.min_duration_ms,
            size=self.size,
        )


class CustomerIn(Schema):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    domain_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    tier: CustomerTier
    reason: str = Field("", max_length=500)


class CustomerPatch(Schema):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=120)
    tier: CustomerTier | None = None
    reason: str = Field("", max_length=500)
