"""core-api's clients of the cloud's API (OpenStack) and of Alertmanager (F17, ADR-0048 §1).
Transport only: a read answers its JSON, or raises `BackendNotFound` for a 404 and
`BackendUnavailable` for anything else."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from apps.infra.models import InfraBackend

logger = logging.getLogger(__name__)

Params = Mapping[str, str | int | bool]


class BackendUnavailable(Exception):
    """A backend that didn't answer, answered an error, or answered something unreadable."""

    def __init__(self, backend: InfraBackend, message: str) -> None:
        super().__init__(f"{backend.value}: {message}")
        self.backend = backend


class BackendNotFound(Exception):
    """A backend that answered 404."""


def http_client() -> httpx.Client:
    """An HTTP client with the infra connect and read timeouts, following no redirects."""
    timeout = httpx.Timeout(
        settings.INFRA_READ_TIMEOUT_SEC, connect=settings.INFRA_CONNECT_TIMEOUT_SEC
    )
    return httpx.Client(timeout=timeout, follow_redirects=False)


def json_of(backend: InfraBackend, response: httpx.Response) -> Any:
    """A 200's JSON body; raises `BackendNotFound` on a 404, `BackendUnavailable` otherwise."""
    if response.status_code == 404:
        raise BackendNotFound(str(response.request.url.path))
    if response.status_code != 200:
        raise BackendUnavailable(backend, f"answered {response.status_code}")
    try:
        return response.json()
    except ValueError as e:
        raise BackendUnavailable(backend, "answered non-JSON") from e


@dataclass(frozen=True)
class ServiceToken:
    """A Keystone token for core-api's service account and the endpoints its catalog names."""

    value: str
    expires_at: datetime
    endpoints: dict[str, str]

    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()


class OpenStack:
    """The cloud's API as core-api's service account: one token, kept until it expires or is
    refused, and the public endpoint of each service in its catalog."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http
        self._token: ServiceToken | None = None
        self._lock = threading.Lock()

    def get(self, service: str, path: str, params: Params | None = None) -> Any:
        """GETs `path` from the catalog's `service` endpoint, signing in again once if the
        token is refused."""
        response = self.send(self.token(), service, path, params)
        if response.status_code == 401:
            response = self.send(self.token(renew=True), service, path, params)
        return json_of(InfraBackend.CLOUD, response)

    def token(self, *, renew: bool = False) -> ServiceToken:
        with self._lock:
            if renew or self._token is None or self._token.is_expired():
                self._token = self.sign_in()
            return self._token

    def sign_in(self) -> ServiceToken:
        """A system-scoped token for the service account."""
        body = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": settings.OPENSTACK_SERVICE_USER,
                            "domain": {"name": settings.OPENSTACK_SERVICE_DOMAIN},
                            "password": settings.OPENSTACK_SERVICE_PASSWORD,
                        }
                    },
                },
                "scope": {"system": {"all": True}},
            }
        }
        try:
            response = self.http.post(f"{settings.OPENSTACK_AUTH_URL}/auth/tokens", json=body)
        except httpx.HTTPError as e:
            raise BackendUnavailable(InfraBackend.CLOUD, f"Keystone: {type(e).__name__}") from e
        if response.status_code == 401:
            logger.error("infra: Keystone refused core-api's service account")
        if response.status_code != 201:
            raise BackendUnavailable(
                InfraBackend.CLOUD, f"Keystone answered {response.status_code}"
            )
        try:
            token = response.json()["token"]
            return ServiceToken(
                value=response.headers["X-Subject-Token"],
                expires_at=datetime.fromisoformat(token["expires_at"]),
                endpoints={
                    entry["type"]: endpoint["url"].rstrip("/")
                    for entry in token["catalog"]
                    for endpoint in entry["endpoints"]
                    if endpoint["interface"] == "public"
                },
            )
        except (KeyError, TypeError, ValueError) as e:
            raise BackendUnavailable(InfraBackend.CLOUD, "Keystone's token is unreadable") from e

    def send(
        self, token: ServiceToken, service: str, path: str, params: Params | None
    ) -> httpx.Response:
        base = token.endpoints.get(service)
        if base is None:
            raise BackendUnavailable(InfraBackend.CLOUD, f"the catalog names no {service}")
        try:
            return self.http.get(
                f"{base}{path}", params=params, headers={"X-Auth-Token": token.value}
            )
        except httpx.HTTPError as e:
            raise BackendUnavailable(InfraBackend.CLOUD, f"{service}: {type(e).__name__}") from e


class Alertmanager:
    """Alertmanager's v2 API: alerts and silences, read only."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def get(self, path: str, params: Params | None = None) -> Any:
        try:
            response = self.http.get(f"{settings.ALERTMANAGER_URL}/api/v2{path}", params=params)
        except httpx.HTTPError as e:
            raise BackendUnavailable(InfraBackend.ALERTMANAGER, type(e).__name__) from e
        return json_of(InfraBackend.ALERTMANAGER, response)


@cache
def openstack() -> OpenStack:
    """The process's cloud client."""
    return OpenStack(http_client())


@cache
def alertmanager() -> Alertmanager:
    """The process's Alertmanager client."""
    return Alertmanager(http_client())
