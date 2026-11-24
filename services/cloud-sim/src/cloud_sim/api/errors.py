"""Error bodies in each OpenStack service's own shape."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

_NOVA_KEYS = {400: "badRequest", 404: "itemNotFound", 409: "conflictingRequest"}
_TITLES = {400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 409: "Conflict"}


class ApiError(Exception):
    """An error answer: its status and its service's body."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        super().__init__(status)
        self.status = status
        self.body = body


def keystone_error(status: int, message: str) -> ApiError:
    return ApiError(
        status, {"error": {"code": status, "message": message, "title": _TITLES.get(status, "")}}
    )


def nova_error(status: int, message: str) -> ApiError:
    """A Nova error; Cinder's have the same shape."""
    return ApiError(
        status, {_NOVA_KEYS.get(status, "computeFault"): {"code": status, "message": message}}
    )


def neutron_error(status: int, kind: str, message: str) -> ApiError:
    return ApiError(status, {"NeutronError": {"type": kind, "message": message, "detail": ""}})


async def handle(_: Request, error: Exception) -> JSONResponse:
    """Answers an `ApiError` with its status and body."""
    assert isinstance(error, ApiError)
    return JSONResponse(error.body, status_code=error.status)
