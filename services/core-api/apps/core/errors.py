"""The shared refusal: an HTTP status, a code from an app's StrEnum, a message and details (BR-X-08)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class CodedError(Exception):
    """A request core-api refuses, answered as {"code", "message", "details"} by `config/urls.py`."""

    def __init__(self, status: int, code: StrEnum, message: str = "", details: Any = None) -> None:
        super().__init__(message or code.value)
        self.status = status
        self.code = code
        self.message = message or code.value
        self.details = details
