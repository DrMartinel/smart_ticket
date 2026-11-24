"""Sends planned log lines and traces over OTLP, one OpenTelemetry resource per server."""

from __future__ import annotations

from datetime import datetime

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode

from cloud_sim.cloud import Cloud, Server
from cloud_sim.telemetry.signals import Emission, Severity, SpanPlan

_SEVERITY = {
    Severity.INFO: SeverityNumber.INFO,
    Severity.WARN: SeverityNumber.WARN,
    Severity.ERROR: SeverityNumber.ERROR,
}

# The resource attribute every log line and span carries its project in.
PROJECT_ATTRIBUTE = "openstack.project_id"


def resource_of(cloud: Cloud, server: Server) -> Resource:
    """The OpenTelemetry resource a server's signals carry."""
    project = cloud.projects[server.project_id]
    return Resource.create(
        {
            "service.name": server.workload,
            "host.name": server.name,
            "host.id": server.id,
            "cloud.provider": "openstack",
            "cloud.region": cloud.region,
            "deployment.environment.name": project.environment,
            PROJECT_ATTRIBUTE: project.id,
            "openstack.project_name": project.name,
        }
    )


class Exporter:
    """Keeps one tracer and one logger provider per server and sends emissions through them."""

    def __init__(self, cloud: Cloud, *, spans: SpanExporter, logs: LogRecordExporter) -> None:
        self.cloud = cloud
        self._spans, self._logs = spans, logs
        self._tracers: dict[str, TracerProvider] = {}
        self._loggers: dict[str, LoggerProvider] = {}

    @classmethod
    def otlp(cls, cloud: Cloud, endpoint: str) -> Exporter:
        """An exporter sending to an OTLP/HTTP endpoint."""
        base = endpoint.rstrip("/")
        return cls(
            cloud,
            spans=OTLPSpanExporter(endpoint=f"{base}/v1/traces"),
            logs=OTLPLogExporter(endpoint=f"{base}/v1/logs"),
        )

    def send(self, emission: Emission) -> None:
        for line in emission.logs:
            self._logger(line.server_id).get_logger("cloud-sim").emit(
                timestamp=_ns(line.at),
                severity_number=_SEVERITY[line.severity],
                severity_text=line.severity.value,
                body=line.body,
            )
        for root in emission.traces:
            self._span(root, parent=None)

    def flush(self) -> None:
        """Sends whatever is still batched."""
        for provider in self._tracers.values():
            provider.force_flush()
        for logger in self._loggers.values():
            logger.force_flush()

    def shutdown(self) -> None:
        for provider in self._tracers.values():
            provider.shutdown()
        for logger in self._loggers.values():
            logger.shutdown()

    def _span(self, plan: SpanPlan, parent: trace.Span | None) -> None:
        tracer = self._tracer(plan.server_id).get_tracer("cloud-sim")
        context = trace.set_span_in_context(parent) if parent is not None else None
        kind = trace.SpanKind.SERVER if parent is None else trace.SpanKind.CLIENT
        start = _ns(plan.start)
        span = tracer.start_span(
            plan.name, context=context, kind=kind, start_time=start, attributes=plan.attributes
        )
        if plan.error:
            span.set_status(Status(StatusCode.ERROR))
        for child in plan.children:
            self._span(child, parent=span)
        span.end(end_time=start + int(plan.duration_ms * 1_000_000))

    def _tracer(self, server_id: str) -> TracerProvider:
        if server_id not in self._tracers:
            provider = TracerProvider(
                resource=resource_of(self.cloud, self.cloud.servers[server_id])
            )
            provider.add_span_processor(BatchSpanProcessor(self._spans))
            self._tracers[server_id] = provider
        return self._tracers[server_id]

    def _logger(self, server_id: str) -> LoggerProvider:
        if server_id not in self._loggers:
            provider = LoggerProvider(
                resource=resource_of(self.cloud, self.cloud.servers[server_id])
            )
            provider.add_log_record_processor(BatchLogRecordProcessor(self._logs))
            self._loggers[server_id] = provider
        return self._loggers[server_id]


def _ns(at: datetime) -> int:
    return int(at.timestamp() * 1_000_000_000)
