"""Test helpers: a fake clock, test settings, a token request and the `Sim` handle the tests drive."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cloud_sim.cloud import Cloud
from cloud_sim.config import Settings

SERVICE_USER, SERVICE_PASSWORD = "smart-ticket-test", "test-only-password"
TRANSITION_SEC = 10.0


class FakeClock:
    """A clock that moves only when told."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class Sim:
    """A running app with its cloud, clock, admin headers and exporters."""

    client: TestClient
    cloud: Cloud
    clock: FakeClock
    headers: dict[str, str]
    spans: InMemorySpanExporter
    logs: InMemoryLogRecordExporter

    def id_of(self, kind: str, name: str) -> str:
        """The seed id of a server, volume, network or project by its name."""
        tables: dict[str, dict[str, Any]] = {
            "server": self.cloud.servers,
            "volume": self.cloud.volumes,
            "network": self.cloud.networks,
            "project": self.cloud.projects,
        }
        return next(i for i, row in tables[kind].items() if row.name == name)


def settings() -> Settings:
    """Settings for tests, with no `.env`."""
    return Settings.model_validate(
        {
            "OPENSTACK_SERVICE_USER": SERVICE_USER,
            "OPENSTACK_SERVICE_PASSWORD": SERVICE_PASSWORD,
            "CLOUD_SIM_OTLP_ENDPOINT": "http://apm.invalid:8200",
            "CLOUD_SIM_TICK_SEC": 5,
            "CLOUD_SIM_TRANSITION_SEC": TRANSITION_SEC,
            "CLOUD_SIM_TOKEN_TTL_SEC": 3600,
        }
    )


def token_body(user: str = SERVICE_USER, password: str = SERVICE_PASSWORD) -> dict[str, Any]:
    """A Keystone password request for a system-scoped token."""
    return {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {"name": user, "domain": {"name": "Default"}, "password": password}
                },
            },
            "scope": {"system": {"all": True}},
        }
    }
