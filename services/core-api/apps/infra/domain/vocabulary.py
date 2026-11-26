"""The refusals an infra route answers with (F17 §h.2, BR-X-08)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from apps.core.errors import CodedError


class InfraRefusal(StrEnum):
    NOT_FOUND = "infra_not_found"
    QUERY_REFUSED = "infra_query_refused"
    SCOPE_UNAVAILABLE = "infra_scope_unavailable"
    BACKEND_UNAVAILABLE = "infra_backend_unavailable"


class QueryCheck(StrEnum):
    """The check a refused query failed, in `details.reason`."""

    RANGE = "range"
    STEP = "step"
    SERIES = "series"
    SIZE = "size"
    FIELD = "field"
    DATASET = "dataset"
    FUNCTION = "function"
    BACKEND_REFUSED = "backend_refused"


_STATUS = {
    InfraRefusal.NOT_FOUND: 404,
    InfraRefusal.QUERY_REFUSED: 422,
    InfraRefusal.SCOPE_UNAVAILABLE: 424,
    InfraRefusal.BACKEND_UNAVAILABLE: 424,
}


class InfraError(CodedError):
    """An infra request core-api refuses."""

    code: InfraRefusal

    def __init__(self, code: InfraRefusal, message: str, details: Any = None) -> None:
        super().__init__(_STATUS[code], code, message, details)


class QueryRefused(Exception):
    """A query that failed a check before or after it ran."""

    def __init__(self, check: QueryCheck, message: str) -> None:
        super().__init__(message)
        self.check = check
