"""Fixtures: a cloud-sim app on a fake clock with in-memory exporters, and a bare cloud."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cloud_sim.cloud import Cloud
from cloud_sim.main import create_app
from cloud_sim.seed import Seed
from cloud_sim.telemetry.export import Exporter
from cloud_sim.testing import SERVICE_PASSWORD, SERVICE_USER, FakeClock, Sim, settings, token_body


@pytest.fixture
def sim() -> Iterator[Sim]:
    clock = FakeClock()
    spans, logs = InMemorySpanExporter(), InMemoryLogRecordExporter()
    app = create_app(
        settings(),
        clock=clock,
        exporter=lambda cloud: Exporter(cloud, spans=spans, logs=logs),
        tick=False,
    )
    with TestClient(app) as client:
        reply = client.post("/identity/v3/auth/tokens", json=token_body())
        assert reply.status_code == 201
        yield Sim(
            client,
            app.state.cloud,
            clock,
            {"X-Auth-Token": reply.headers["X-Subject-Token"]},
            spans,
            logs,
        )


@pytest.fixture
def cloud() -> Cloud:
    return Cloud(
        Seed.packaged(),
        clock=FakeClock(),
        transition_sec=0,
        service_user=SERVICE_USER,
        service_password=SERVICE_PASSWORD,
    )
