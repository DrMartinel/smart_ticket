"""The lifecycle's refusal, carried to the API as `{code, message, details}`."""

from __future__ import annotations

from typing import Any

from apps.core.errors import CodedError
from apps.lifecycle.utils.vocabulary import FailureCode


class LifecycleError(CodedError):
    """A request the lifecycle refuses; callers return it to the client as `status`, never retry it."""

    code: FailureCode

    def __init__(
        self, status: int, code: FailureCode, message: str = "", details: Any = None
    ) -> None:
        super().__init__(status, code, message, details)
