"""The requester's words for where a ticket stands, and the refusals of the requester endpoints (F3)."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from apps.accounts.models import Language
from apps.core.errors import CodedError
from apps.lifecycle.utils.vocabulary import StatusKind

if TYPE_CHECKING:
    from apps.lifecycle.models import WorkflowStatus


class RequesterRefusal(StrEnum):
    TICKET_NOT_FOUND = "ticket_not_found"
    TICKET_CLOSED = "ticket_closed"
    TICKET_IN_TRIAGE = "ticket_in_triage"
    NOT_RESOLVED = "not_resolved"
    REASON_REQUIRED = "reason_required"
    RATING_WINDOW_CLOSED = "rating_window_closed"
    BAD_SCORE = "bad_score"


class RequesterError(CodedError):
    """A requester request core-api refuses."""


class CommentState(StrEnum):
    """How a comment shows in the requester's thread."""

    SHOWN = "shown"
    # Its masking failed; a reviewer checks it first (UC-F3-03 3y).
    CHECKING = "checking"
    # A reviewer discarded it; the requester is asked to send it again.
    DISCARDED = "discarded"


# Status kind -> (vi, en) (F3 §g, BR-F3-05, ADR-0040).
_LABELS = {
    StatusKind.BACKLOG.value: ("Đang tiếp nhận", "Received"),
    StatusKind.ACTIVE.value: ("Đang xử lý", "In progress"),
    StatusKind.COMPLETED.value: ("Đã giải quyết", "Resolved"),
}
_WAITING_FOR_YOU = ("Chờ bạn phản hồi", "Waiting for you")


def status_label(status: WorkflowStatus | None, language: str) -> str:
    """The requester's label for a status: from its kind, never its workflow name."""
    if status is not None and status.pauses_sla and not status.is_completed:
        pair = _WAITING_FOR_YOU
    else:
        pair = _LABELS[status.kind if status else StatusKind.BACKLOG.value]
    return pair[1] if language == Language.EN.value else pair[0]


# Fixed text the system writes in a ticket's thread.
AUTO_CLOSED_COMMENT = "Đóng tự động do không có phản hồi"
RELATED_TO = "Liên quan đến"
