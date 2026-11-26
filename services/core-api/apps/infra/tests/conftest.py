"""Fixtures: cloud-sim running in-process as the cloud, a fake Alertmanager, and NER stubs."""

from __future__ import annotations

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

from apps.infra.utils import inventory
from apps.infra.utils.clients import Alertmanager, OpenStack

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
        monkeypatch.setattr(inventory, "openstack", lambda: OpenStack(cast(httpx.Client, client)))
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

        monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", detect)

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
