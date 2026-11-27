"""The lifecycle's refusals, carried to the API as `{code, message, details}`."""

from __future__ import annotations

from typing import Any

from apps.core.errors import CodedError
from apps.lifecycle.domain.vocabulary import FailureCode, RuleRefusal


class LifecycleError(CodedError):
    """A request the lifecycle refuses; callers return it to the client as `status`, never retry it."""

    code: FailureCode

    def __init__(
        self, status: int, code: FailureCode, message: str = "", details: Any = None
    ) -> None:
        super().__init__(status, code, message, details)


class WorkflowRuleError(CodedError):
    """A workflow rule request core-api refuses (ADR-0055)."""

    code: RuleRefusal

    def __init__(
        self, status: int, code: RuleRefusal, message: str = "", details: Any = None
    ) -> None:
        super().__init__(status, code, message, details)
