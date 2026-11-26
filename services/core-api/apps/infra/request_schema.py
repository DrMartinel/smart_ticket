"""Request shapes for the infra queries (F17 §h.1), whose catalog and caps are checked when the
query compiles, or for raw PromQL when Prometheus has parsed it, the customer routes' bodies
(F17 §o.9), and the changes' bodies (F17 §h.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from ninja import Field, Schema
from pydantic import ConfigDict, IPvAnyNetwork, model_validator

from apps.infra.domain.changes import RuleSpec
from apps.infra.domain.promql import PromQLQuery
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
    project_id: str | None = Field(None, min_length=1)

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


class PromQLIn(Schema):
    promql: str = Field(min_length=1, max_length=2000)
    start: datetime
    end: datetime
    step_seconds: int = Field(ge=1)
    project_id: str | None = Field(None, min_length=1)

    def query(self) -> PromQLQuery:
        return PromQLQuery(
            text=self.promql, window=Window(self.start, self.end), step_seconds=self.step_seconds
        )


class LogSearchIn(Schema):
    start: datetime
    end: datetime
    dataset: str = "instance"
    text: str | None = Field(default=None, max_length=500)
    filters: dict[str, list[str]] = {}
    size: int | None = Field(default=None, ge=1)
    project_id: str | None = Field(None, min_length=1)

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
    project_id: str | None = Field(None, min_length=1)

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


# ── changes (F17 §h.1, BR-F17-08, BR-F17-11) ──


class StaffChangeIn(Schema):
    """A staff change's body: the open ticket it is for."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    public_id: str = Field(min_length=1, max_length=32)


class SoftRebootIn(StaffChangeIn):
    type: Literal["soft"] = "soft"


class MySoftRebootIn(Schema):
    model_config = ConfigDict(extra="forbid")

    type: Literal["soft"] = "soft"


class AttachVolumeIn(StaffChangeIn):
    server_id: str = Field(min_length=1, max_length=64)


class SecurityRuleIn(StaffChangeIn):
    direction: Literal["ingress", "egress"]
    ethertype: Literal["IPv4", "IPv6"] = "IPv4"
    protocol: Literal["tcp", "udp", "icmp"] | None = None
    port_range_min: int | None = Field(default=None, ge=1, le=65535)
    port_range_max: int | None = Field(default=None, ge=1, le=65535)
    remote_ip_prefix: IPvAnyNetwork | None = None

    @model_validator(mode="after")
    def ports_need_a_protocol(self) -> Self:
        low, high = self.port_range_min, self.port_range_max
        if (low, high) != (None, None) and self.protocol not in ("tcp", "udp"):
            raise ValueError("a port range needs protocol tcp or udp")
        if low is not None and high is not None and low > high:
            raise ValueError("port_range_min is above port_range_max")
        return self

    def rule(self) -> RuleSpec:
        return RuleSpec(
            direction=self.direction,
            ethertype=self.ethertype,
            protocol=self.protocol,
            port_min=self.port_range_min,
            port_max=self.port_range_max,
            remote_ip_prefix=str(self.remote_ip_prefix) if self.remote_ip_prefix else None,
        )


class SecurityRuleRemoveIn(StaffChangeIn):
    rule_id: str = Field(min_length=1, max_length=64)
