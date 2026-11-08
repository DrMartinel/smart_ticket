"""
The agent's one HTTP client to core-api: each call is one attempt, as the
signed-in user, with the turn's agent token. No retry, a write included.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import httpx
from pydantic import SecretStr

from ai_engine.core.config import settings


class ToolFailed(Exception):
    """A read failed, or a write was never sent."""


class OutcomeUnknown(Exception):
    """A write was sent and whether it landed is not known."""


@dataclass(frozen=True)
class Reply:
    """core-api's answer to one call."""

    status: int
    body: Any


class CoreApi:
    """core-api at `base_url`, called as the person an agent token stands for."""

    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url

    def send(
        self,
        method: str,
        path: str,
        token: SecretStr,
        tool: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Reply:
        """One request on behalf of `tool`. Raises `ToolFailed` or, for a write, `OutcomeUnknown`."""
        try:
            response = self._http.request(
                method,
                path,
                params=params,
                json=json,
                headers={
                    "Authorization": f"Bearer {token.get_secret_value()}",
                    "X-Agent-Tool": tool,
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            raise ToolFailed(type(e).__name__) from None
        except httpx.TransportError as e:
            if method == "GET":
                raise ToolFailed(type(e).__name__) from None
            raise OutcomeUnknown(type(e).__name__) from None
        if response.status_code >= 500:
            if method == "GET":
                raise ToolFailed(f"HTTP {response.status_code}")
            raise OutcomeUnknown(f"HTTP {response.status_code}")
        try:
            body = response.json() if response.content else None
        except ValueError:
            raise ToolFailed("unparseable reply") from None
        return Reply(response.status_code, body)

    def wait(self, seconds: float) -> None:
        """Sleeps between polls."""
        time.sleep(seconds)

    @cached_property
    def _http(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                settings.agent_tool_read_timeout_sec,
                connect=settings.agent_tool_connect_timeout_sec,
            ),
        )


core_api = CoreApi(base_url=settings.core_api_url)
