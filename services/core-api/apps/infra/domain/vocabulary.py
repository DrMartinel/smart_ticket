"""The refusals an infra route answers with (F17 §h.2, BR-X-08)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from apps.core.errors import CodedError, OutcomeUnknownError


class InfraRefusal(StrEnum):
    NOT_FOUND = "infra_not_found"
    QUERY_REFUSED = "infra_query_refused"
    SCOPE_UNAVAILABLE = "infra_scope_unavailable"
    BACKEND_UNAVAILABLE = "infra_backend_unavailable"
    TICKET_REQUIRED = "infra_ticket_required"
    STATE_CHANGED = "infra_state_changed"
    CHANGE_REFUSED = "infra_change_refused"
    OUTCOME_UNKNOWN = "infra_outcome_unknown"
    CUSTOMER_EXISTS = "customer_exists"
    UNKNOWN_DOMAIN = "unknown_domain"
    REASON_REQUIRED = "reason_required"


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
    InfraRefusal.TICKET_REQUIRED: 409,
    InfraRefusal.STATE_CHANGED: 409,
    InfraRefusal.CHANGE_REFUSED: 422,
    InfraRefusal.OUTCOME_UNKNOWN: 502,
    InfraRefusal.CUSTOMER_EXISTS: 409,
    InfraRefusal.UNKNOWN_DOMAIN: 422,
    InfraRefusal.REASON_REQUIRED: 422,
}


class InfraError(CodedError):
    """An infra request core-api refuses."""

    code: InfraRefusal

    def __init__(self, code: InfraRefusal, message: str, details: Any = None) -> None:
        super().__init__(_STATUS[code], code, message, details)


class InfraOutcomeUnknown(InfraError, OutcomeUnknownError):
    """A change sent to the cloud whose answer was lost; it is never sent again."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(InfraRefusal.OUTCOME_UNKNOWN, message, details)


class QueryRefused(Exception):
    """A query that failed a check before or after it ran."""

    def __init__(self, check: QueryCheck, message: str) -> None:
        super().__init__(message)
        self.check = check
