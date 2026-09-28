"""
Response shapes for the mock ITSM endpoints.
"""

from __future__ import annotations

from typing import Any

from ninja import Schema


class RunbookOut(Schema):
    title: str
    required_fields: list[str]


class RunbookExecutionOut(Schema):
    id: int
    runbook_id: str
    status: str
    result: dict[str, Any]
