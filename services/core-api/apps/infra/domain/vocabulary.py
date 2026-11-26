"""The refusals an infra route answers with (F17 §h.2, BR-X-08)."""

from __future__ import annotations

from enum import StrEnum

from apps.core.errors import CodedError


class InfraRefusal(StrEnum):
    NOT_FOUND = "infra_not_found"
    SCOPE_UNAVAILABLE = "infra_scope_unavailable"
    BACKEND_UNAVAILABLE = "infra_backend_unavailable"


_STATUS = {
    InfraRefusal.NOT_FOUND: 404,
    InfraRefusal.SCOPE_UNAVAILABLE: 424,
    InfraRefusal.BACKEND_UNAVAILABLE: 424,
}


class InfraError(CodedError):
    """An infra request core-api refuses."""

    code: InfraRefusal

    def __init__(self, code: InfraRefusal, message: str) -> None:
        super().__init__(_STATUS[code], code, message)
