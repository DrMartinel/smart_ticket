"""
Request bodies for the review endpoints.
"""

from __future__ import annotations

import uuid
from typing import Literal

from ninja import Schema


class DecisionIn(Schema):
    action_taken: str
    kb_verdict: str | None = None
    category_verdict: str | None = None
    corrected_category: str | None = None
    corrected_kb_id: uuid.UUID | None = None
    override_reason: str | None = None
    time_spent_sec: int


class CommentDecisionIn(Schema):
    """Show a held comment to staff, or discard it (F3 UC-F3-03 3y)."""

    choice: Literal["show", "discard"]
