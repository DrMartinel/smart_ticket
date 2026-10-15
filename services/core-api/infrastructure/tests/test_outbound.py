"""The webhook client refuses destinations outside the allow-list and addresses that are never safe."""

import socket

import httpx
import pytest

from infrastructure.outbound import OutboundHttp, OutboundRefused, OutboundUnavailable

_HttpxClient = httpx.Client


def resolving_to(monkeypatch, address: str) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))],
    )


@pytest.fixture
def allowed(settings):
    settings.LIFECYCLE_WEBHOOK_ALLOWED_HOSTS = ["hooks.example.com"]


def test_a_host_off_the_allow_list_is_refused(allowed):
    with pytest.raises(OutboundRefused, match="not in LIFECYCLE_WEBHOOK_ALLOWED_HOSTS"):
        OutboundHttp().check_destination("https://evil.example.net/x")


@pytest.mark.parametrize("address", ["169.254.169.254", "0.0.0.0", "224.0.0.1", "fe80::1"])
def test_an_allowed_host_resolving_to_an_unsafe_address_is_refused(allowed, monkeypatch, address):
    resolving_to(monkeypatch, address)

    with pytest.raises(OutboundRefused, match="refused address"):
        OutboundHttp().check_destination("https://hooks.example.com/x")


def test_a_non_http_url_is_refused(allowed):
    with pytest.raises(OutboundRefused):
        OutboundHttp().check_destination("file:///etc/passwd")


def test_an_unresolvable_host_is_transient(allowed, monkeypatch):
    def fail(*a, **kw):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)

    with pytest.raises(OutboundUnavailable):
        OutboundHttp().check_destination("https://hooks.example.com/x")


def serve(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    class Stub(_HttpxClient):
        def __init__(self, *a, **kw):
            assert kw["follow_redirects"] is False
            super().__init__(*a, **{**kw, "transport": transport})

    monkeypatch.setattr("infrastructure.outbound.httpx.Client", Stub)


def test_an_answer_is_cut_at_the_size_limit(allowed, monkeypatch, settings):
    settings.LIFECYCLE_HTTP_MAX_RESPONSE_BYTES = 10
    resolving_to(monkeypatch, "93.184.216.34")
    serve(monkeypatch, lambda request: httpx.Response(500, content=b"x" * 100))

    response = OutboundHttp().send("https://hooks.example.com/x", method="POST", json_body={})

    assert response.status == 500
    assert response.text == "x" * 10


def test_a_transport_failure_is_transient(allowed, monkeypatch):
    resolving_to(monkeypatch, "93.184.216.34")

    def refuse(request):
        raise httpx.ConnectError("refused")

    serve(monkeypatch, refuse)

    with pytest.raises(OutboundUnavailable):
        OutboundHttp().send("https://hooks.example.com/x", method="POST")
