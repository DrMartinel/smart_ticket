"""The cloud client's service token: kept, renewed when expired or refused, never retried
twice (F17 FR-F17-001); and what a change's answer says: made, refused, never sent or
unknown."""

from __future__ import annotations

import httpx
import pytest

from apps.infra.tests.conftest import FakeCloud, mock_http
from apps.infra.clients.backends import (
    BackendConflict,
    BackendNotFound,
    BackendRefused,
    BackendUnavailable,
    ChangeOutcomeUnknown,
    OpenStack,
)

SERVERS = "/compute/servers/detail"


@pytest.fixture(autouse=True)
def auth_url(settings):
    settings.OPENSTACK_AUTH_URL = "http://cloud.test/identity/v3"


def ok() -> httpx.Response:
    return httpx.Response(200, json={"servers": []})


def test_a_token_is_kept_between_reads():
    cloud = FakeCloud({SERVERS: [ok(), ok()]})
    client = OpenStack(cloud.http())

    client.get("compute", "/servers/detail")
    client.get("compute", "/servers/detail")

    assert cloud.sign_ins == 1


def test_an_expired_token_is_renewed():
    cloud = FakeCloud({SERVERS: [ok(), ok()]}, expires_at="2000-01-01T00:00:00+00:00")
    client = OpenStack(cloud.http())

    client.get("compute", "/servers/detail")
    client.get("compute", "/servers/detail")

    assert cloud.sign_ins == 2


def test_a_refused_token_is_renewed_once():
    cloud = FakeCloud({SERVERS: [httpx.Response(401), ok()]})

    assert OpenStack(cloud.http()).get("compute", "/servers/detail") == {"servers": []}
    assert cloud.sign_ins == 2


def test_a_token_refused_twice_is_unavailable_not_retried_again():
    cloud = FakeCloud({SERVERS: [httpx.Response(401), httpx.Response(401)]})

    with pytest.raises(BackendUnavailable):
        OpenStack(cloud.http()).get("compute", "/servers/detail")
    assert cloud.sign_ins == 2


def test_a_404_is_not_found_and_a_500_is_unavailable():
    cloud = FakeCloud({SERVERS: [httpx.Response(404), httpx.Response(500)]})
    client = OpenStack(cloud.http())

    with pytest.raises(BackendNotFound):
        client.get("compute", "/servers/detail")
    with pytest.raises(BackendUnavailable):
        client.get("compute", "/servers/detail")


def test_a_service_the_catalog_does_not_name_is_unavailable():
    with pytest.raises(BackendUnavailable):
        OpenStack(FakeCloud({}).http()).get("network", "/v2.0/networks")


def test_a_refused_service_account_is_unavailable():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(BackendUnavailable):
        OpenStack(mock_http(refuse)).get("compute", "/x")


# ── changes ──

ACTION = "/compute/servers/s1/action"
REBOOT = {"reboot": {"type": "SOFT"}}


def failing(error: type[httpx.TransportError]) -> httpx.Client:
    """A cloud whose every change fails with `error`."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == ACTION:
            raise error("failed", request=request)
        return FakeCloud({}).handle(request)

    return mock_http(handle)


def test_a_change_answered_5xx_may_have_been_made():
    cloud = FakeCloud({ACTION: [httpx.Response(503)]})

    with pytest.raises(ChangeOutcomeUnknown):
        OpenStack(cloud.http()).change("POST", "compute", "/servers/s1/action", REBOOT)


def test_a_change_whose_answer_times_out_may_have_been_made():
    with pytest.raises(ChangeOutcomeUnknown):
        OpenStack(failing(httpx.ReadTimeout)).change(
            "POST", "compute", "/servers/s1/action", REBOOT
        )


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
def test_a_change_that_cannot_connect_was_never_sent(error):
    with pytest.raises(BackendUnavailable):
        OpenStack(failing(error)).change("POST", "compute", "/servers/s1/action", REBOOT)


def test_a_change_refused_for_its_token_is_sent_again_once():
    cloud = FakeCloud({ACTION: [httpx.Response(401), httpx.Response(202)]})

    OpenStack(cloud.http()).change("POST", "compute", "/servers/s1/action", REBOOT)

    assert cloud.sign_ins == 2
    assert cloud.answers[ACTION] == []


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, BackendNotFound), (409, BackendConflict), (400, BackendRefused)],
)
def test_a_change_the_cloud_refuses_names_why(status, error):
    cloud = FakeCloud({ACTION: [httpx.Response(status)]})

    with pytest.raises(error):
        OpenStack(cloud.http()).change("POST", "compute", "/servers/s1/action", REBOOT)
