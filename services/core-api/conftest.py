import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import numpy as np
import pytest

from apps.core.testing import api_client_for


@pytest.fixture
def manager_user(django_user_model):
    u = django_user_model.objects.create_user(username="mgr", password="x", role="manager")
    return u


@pytest.fixture
def employee_user(django_user_model):
    u = django_user_model.objects.create_user(username="emp", password="x", role="employee")
    return u


@pytest.fixture
def technician_user(django_user_model):
    u = django_user_model.objects.create_user(username="tech", password="x", role="technician")
    return u


@pytest.fixture
def api_as():
    """`api_as(user)` is a test client that sends a real JWT for `user`
    (`apps.core.testing.api_client_for`)."""

    return api_client_for


# Captured at import: `serve_ai_engine` patches these names on the httpx
# module, so a second call inside one test (the autouse fixture below, then
# the test's own) must subclass the real clients, not the previous stub.
_HttpxClient = httpx.Client
_HttpxAsyncClient = httpx.AsyncClient


@dataclass
class AIEngineCalls:
    """What core-api sent to the stubbed ai-engine: each request, and the
    timeout each client was built with."""

    requests: list[httpx.Request] = field(default_factory=list)
    timeouts: list[httpx.Timeout] = field(default_factory=list)


@pytest.fixture
def serve_ai_engine(monkeypatch):
    """`serve_ai_engine(handler)` answers every call `AIEngineClient` makes
    with `handler(request)`, which returns an `httpx.Response` or raises an
    httpx error to simulate an outage. Returns an `AIEngineCalls` record.

    Only the transport is swapped: URL building, timeouts, the wire schema
    and error handling all run for real.
    """

    def serve(handler: Callable[[httpx.Request], httpx.Response]) -> AIEngineCalls:
        calls = AIEngineCalls()

        def record(request: httpx.Request) -> httpx.Response:
            calls.requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(record)

        class StubClient(_HttpxClient):
            def __init__(self, *a, **kw):
                calls.timeouts.append(kw["timeout"])
                super().__init__(*a, **{**kw, "transport": transport})

        class StubAsyncClient(_HttpxAsyncClient):
            def __init__(self, *a, **kw):
                calls.timeouts.append(kw["timeout"])
                super().__init__(*a, **{**kw, "transport": transport})

        monkeypatch.setattr("infrastructure.ai_engine.httpx.Client", StubClient)
        monkeypatch.setattr("infrastructure.ai_engine.httpx.AsyncClient", StubAsyncClient)
        return calls

    return serve


def _deterministic_vector(text: str) -> list[float]:
    """Same text, same unit vector; different texts, unrelated vectors."""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    vec = np.random.default_rng(seed).normal(size=1024)
    return (vec / np.linalg.norm(vec)).tolist()


def _offline_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/embed":
        text = json.loads(request.content)["text"]
        return httpx.Response(200, json={"vector": _deterministic_vector(text), "model": "test"})
    raise httpx.ConnectError(f"ai-engine is offline in tests: {request.url.path}")


@pytest.fixture(autouse=True)
def _offline_ai_engine(serve_ai_engine):
    """No test reaches a real ai-engine, even one running locally.
    `/v1/embed` answers deterministically, so KB ingestion, seeding and
    few-shot creation work. Every other call fails as unreachable, which is
    the path core-api must already handle (HITL / MASK_FAILED). A test that
    needs other answers calls `serve_ai_engine` itself, which replaces this."""

    return serve_ai_engine(_offline_handler)
