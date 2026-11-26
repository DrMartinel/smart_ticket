"""Fixtures: cloud-sim running in-process as the cloud, fakes for Alertmanager, Prometheus and
Elasticsearch, and NER stubs."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
from cloud_sim.cloud import Cloud
from cloud_sim.main import create_app
from cloud_sim.telemetry.export import Exporter
from cloud_sim.testing import SERVICE_PASSWORD, SERVICE_USER, FakeClock
from cloud_sim.testing import settings as sim_settings
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from urllib.parse import parse_qs

from apps.infra.clients.backends import Alertmanager, Elasticsearch, OpenStack, Prometheus
from apps.infra.services import customers, inventory, observability

# The real client, captured before the root conftest's ai-engine stub replaces `httpx.Client`.
_Client = httpx.Client


def mock_http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """An HTTP client whose every request `handler` answers."""
    return _Client(transport=httpx.MockTransport(handler))


# lan.nt's Keycloak subject, which cloud-sim's Keystone user carries (OQ-F17-01).
LAN_SUBJECT = "0b6f8f2e-3c3a-4a51-9d1e-6a1f3c2b7e41"


@dataclass
class CloudSim:
    """The simulated cloud core-api talks to, and the calls it received."""

    cloud: Cloud
    client: TestClient
    calls: list[str] = field(default_factory=list)

    def id_of(self, table: str, name: str) -> str:
        rows: dict[str, Any] = getattr(self.cloud, table)
        return next(i for i, row in rows.items() if row.name == name)


@pytest.fixture
def cloud_sim(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[CloudSim]:
    app = create_app(
        sim_settings(),
        clock=FakeClock(),
        exporter=lambda cloud: Exporter(
            cloud, spans=InMemorySpanExporter(), logs=InMemoryLogRecordExporter()
        ),
        tick=False,
    )
    settings.OPENSTACK_AUTH_URL = "http://cloud-sim/identity/v3"
    settings.OPENSTACK_SERVICE_DOMAIN = "Default"
    settings.OPENSTACK_SERVICE_USER = SERVICE_USER
    settings.OPENSTACK_SERVICE_PASSWORD = SERVICE_PASSWORD
    settings.OPENSTACK_FEDERATION_IDP = "smart-ticket"
    settings.OPENSTACK_FEDERATION_PROTOCOL = "openid"
    with TestClient(app, base_url="http://cloud-sim") as client:
        sim = CloudSim(app.state.cloud, client)
        client.event_hooks["request"].append(lambda r: sim.calls.append(f"{r.method} {r.url.path}"))
        cloud = OpenStack(cast(httpx.Client, client))
        monkeypatch.setattr(inventory, "openstack", lambda: cloud)
        monkeypatch.setattr(observability, "openstack", lambda: cloud)
        monkeypatch.setattr(customers, "openstack", lambda: cloud)
        yield sim


@dataclass
class FakeCloud:
    """A Keystone that issues tokens expiring at `expires_at`, and scripted answers per path."""

    answers: dict[str, list[httpx.Response]]
    expires_at: str = "2999-01-01T00:00:00+00:00"
    sign_ins: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v3/auth/tokens":
            self.sign_ins += 1
            catalog = [
                {
                    "type": "compute",
                    "endpoints": [{"interface": "public", "url": "http://cloud.test/compute"}],
                }
            ]
            body = {"token": {"expires_at": self.expires_at, "catalog": catalog}}
            return httpx.Response(201, json=body, headers={"X-Subject-Token": f"t{self.sign_ins}"})
        return self.answers[request.url.path].pop(0)

    def http(self) -> httpx.Client:
        return mock_http(self.handle)


@dataclass
class FakeAlertmanager:
    """Alertmanager's v2 API answering `alerts` and `silences`, or failing with `error`."""

    alerts: list[dict[str, Any]] = field(default_factory=list)
    silences: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.error is not None:
            raise self.error
        body = {"/api/v2/alerts": self.alerts, "/api/v2/silences": self.silences}
        return httpx.Response(200, json=body[request.url.path])


@pytest.fixture
def alertmanager(settings: Any, monkeypatch: pytest.MonkeyPatch) -> FakeAlertmanager:
    fake = FakeAlertmanager()
    settings.ALERTMANAGER_URL = "http://alertmanager"
    http = mock_http(fake.handle)
    monkeypatch.setattr(inventory, "alertmanager", lambda: Alertmanager(http))
    return fake


@pytest.fixture
def ner(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[str], Any]], None]:
    """`ner(fn)` makes NER answer `fn(text)`: a list of PII spans, or raise."""

    def use(fn: Callable[[str], Any]) -> None:
        async def detect(text: str) -> Any:
            return fn(text)

        monkeypatch.setattr("apps.tickets.domain.masking.llm_ner", detect)

    use(lambda text: [])
    return use


def alert(name: str, project: str | None, summary: str, **labels: str) -> dict[str, Any]:
    """An Alertmanager v2 alert."""
    return {
        "labels": {
            "alertname": name,
            "severity": "critical",
            **({"project": project} if project else {}),
            **labels,
        },
        "annotations": {"summary": summary},
        "startsAt": "2026-11-26T09:00:00Z",
        "fingerprint": f"fp-{name}-{project}",
        "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
    }


@dataclass
class FakePrometheus:
    """prom-label-proxy answering range queries with `series`, or `status` and `error`; keeps
    the query and the `project` values of every request."""

    series: list[dict[str, Any]] = field(default_factory=list)
    status: int = 200
    error: str = ""
    raises: Exception | None = None
    queries: list[str] = field(default_factory=list)
    projects: list[list[str]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.raises is not None:
            raise self.raises
        form = parse_qs(request.content.decode())
        self.queries.append(form["query"][0])
        self.projects.append(request.url.params.get_list("project"))
        if self.status != 200:
            return httpx.Response(
                self.status, json={"status": "error", "errorType": "bad_data", "error": self.error}
            )
        body = {"status": "success", "data": {"resultType": "matrix", "result": self.series}}
        return httpx.Response(200, json=body)


@pytest.fixture
def prom(settings: Any, monkeypatch: pytest.MonkeyPatch) -> FakePrometheus:
    fake = FakePrometheus()
    settings.PROMETHEUS_URL = "http://prom-label-proxy"
    http = mock_http(fake.handle)
    monkeypatch.setattr(observability, "prometheus", lambda: Prometheus(http))
    return fake


@dataclass
class FakeElasticsearch:
    """Elasticsearch answering every search with `docs`, or failing with `raises`; keeps the
    index and body of every search."""

    docs: list[dict[str, Any]] = field(default_factory=list)
    raises: Exception | None = None
    searches: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.raises is not None:
            raise self.raises
        index = request.url.path.removeprefix("/").removesuffix("/_search")
        self.searches.append((index, json.loads(request.content)))
        hits = [{"_source": d} for d in self.docs]
        return httpx.Response(200, json={"hits": {"total": {"value": len(hits)}, "hits": hits}})

    def bodies(self) -> list[dict[str, Any]]:
        return [body for _, body in self.searches]


@pytest.fixture
def es(settings: Any, monkeypatch: pytest.MonkeyPatch) -> FakeElasticsearch:
    fake = FakeElasticsearch()
    settings.ELASTICSEARCH_URL = "http://elasticsearch"
    http = mock_http(fake.handle)
    monkeypatch.setattr(observability, "elasticsearch", lambda: Elasticsearch(http))
    return fake


def series(project: str, value: float = 0.5, **labels: str) -> dict[str, Any]:
    """A range query's series."""
    return {
        "metric": {"__name__": "cloud_volume_read_latency_seconds", "project": project, **labels},
        "values": [[1764147600, str(value)], [1764147660, str(value)]],
    }


def log_doc(project: str, message: str, server: str = "db-01") -> dict[str, Any]:
    """A log line as the APM Server indexes it."""
    return {
        "@timestamp": "2026-11-26T09:02:00Z",
        "log": {"level": "ERROR"},
        "labels": {"openstack_project_id": project},
        "host": {"name": server, "id": f"id-{server}"},
        "service": {"name": "postgres"},
        "message": message,
    }


def span_doc(project: str, trace_id: str = "t1", **labels: str) -> dict[str, Any]:
    """A request (a transaction) as the APM Server indexes it."""
    return {
        "@timestamp": "2026-11-26T09:02:00Z",
        "trace": {"id": trace_id},
        "transaction": {"id": "tx1", "name": "GET /orders", "duration": {"us": 120000}},
        "labels": {"openstack_project_id": project, **labels},
        "host": {"name": "app-01"},
        "service": {"name": "orders"},
        "event": {"outcome": "success"},
    }
