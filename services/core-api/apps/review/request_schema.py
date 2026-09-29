"""
Request bodies for the review endpoints.
"""

from __future__ import annotations

import uuid

from ninja import Schema


class DecisionIn(Schema):
    action_taken: str
    kb_verdict: str | None = None
    category_verdict: str | None = None
    corrected_category: str | None = None
    corrected_kb_id: uuid.UUID | None = None
    override_reason: str | None = None
    time_spent_sec: int
