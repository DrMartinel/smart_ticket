"""
core-api's client for the webhooks lifecycle actions and notifications call (ADR-0028, ADR-0033). Only
hosts on `LIFECYCLE_WEBHOOK_ALLOWED_HOSTS` are reached, never a link-local,
multicast, reserved or unspecified address, and redirects aren't followed.
Transport only: what a status code means is the action's decision.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from django.conf import settings


class OutboundRefused(Exception):
    """The destination is not allowed; callers fail the run and never retry it."""


class OutboundUnavailable(Exception):
    """The destination could not be reached or didn't answer in time; callers may retry."""


@dataclass(frozen=True)
class OutboundResponse:
    status: int
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class OutboundHttp:
    """Sends one HTTP request to an allowed webhook host."""

    def send(
        self,
        url: str,
        *,
        method: str,
        json_body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> OutboundResponse:
        """Sends `json_body` as JSON, or `content` as is; raises `OutboundRefused` for a
        disallowed destination, `OutboundUnavailable` on transport failure."""
        self.check_destination(url)
        timeout = httpx.Timeout(
            settings.LIFECYCLE_HTTP_READ_TIMEOUT_SEC,
            connect=settings.LIFECYCLE_HTTP_CONNECT_TIMEOUT_SEC,
        )
        limit = settings.LIFECYCLE_HTTP_MAX_RESPONSE_BYTES
        deadline = time.monotonic() + settings.LIFECYCLE_HTTP_TOTAL_TIMEOUT_SEC
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                payload: dict[str, Any] = (
                    {"json": json_body} if content is None else {"content": content}
                )
                with client.stream(method, url, headers=headers, **payload) as response:
                    body = b""
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise OutboundUnavailable(f"{url} took longer than the total timeout")
                        body += chunk
                        if len(body) >= limit:
                            body = body[:limit]
                            break
                    return OutboundResponse(response.status_code, body.decode("utf-8", "replace"))
        except httpx.HTTPError as e:
            raise OutboundUnavailable(str(e)) from e

    def check_url(self, url: str) -> tuple[str, int | None]:
        """The host and port of `url`; raises `OutboundRefused` unless it is http(s) to an
        allowed host on a valid port."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise OutboundRefused(f"not an http(s) URL: {url!r}")
        try:
            port = parsed.port
        except ValueError as e:
            raise OutboundRefused(f"invalid port in {url!r}") from e
        host = parsed.hostname.lower()
        if host not in settings.LIFECYCLE_WEBHOOK_ALLOWED_HOSTS:
            raise OutboundRefused(f"host {host!r} is not in LIFECYCLE_WEBHOOK_ALLOWED_HOSTS")
        return host, port

    def check_destination(self, url: str) -> None:
        """Raises `OutboundRefused` unless `url` is http(s) to an allowed host with a routable address."""
        host, port = self.check_url(url)
        try:
            infos = socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            raise OutboundUnavailable(f"cannot resolve {host!r}: {e}") from e
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if (
                address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or address.is_reserved
            ):
                raise OutboundRefused(f"host {host!r} resolves to a refused address {address}")


# --- the outbound client ---

outbound = OutboundHttp()
