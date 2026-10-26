"""The requester's words for where a ticket stands, and the refusals of the requester endpoints (F3)."""

from __future__ import annotations

from enum import StrEnum

from apps.accounts.models import Language
from apps.core.errors import CodedError


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


# System status base name -> (vi, en) (F3 §g, BR-F3-05).
_LABELS = {
    "Intake": ("Đang tiếp nhận", "Received"),
    "Open": ("Đang chờ xử lý", "Waiting for support"),
    "In progress": ("Đang xử lý", "In progress"),
    "On hold": ("Tạm dừng", "On hold"),
    "Resolved": ("Đã giải quyết", "Resolved"),
    "Closed": ("Đã đóng", "Closed"),
}
_WAITING_FOR_YOU = ("Chờ bạn phản hồi", "Waiting for you")


def status_label(base_name: str | None, pauses_sla: bool, language: str) -> str:
    """The requester's label for a status: from its system status base, never its workflow name."""
    if base_name == "On hold" and pauses_sla:
        pair = _WAITING_FOR_YOU
    else:
        pair = _LABELS.get(base_name or "Intake", _LABELS["Intake"])
    return pair[1] if language == Language.EN.value else pair[0]


# Fixed text the system writes in a ticket's thread.
AUTO_CLOSED_COMMENT = "Đóng tự động do không có phản hồi"
RELATED_TO = "Liên quan đến"
