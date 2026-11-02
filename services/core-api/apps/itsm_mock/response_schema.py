"""Response shapes for the runbook endpoints (F12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Schema


class RunbookOut(Schema):
    code: str
    title: str
    executor: str
    config: dict[str, Any]
    required_fields: list[str]
    target_rule: str
    risk: str
    is_active: bool
    runnable: bool
    approved_by: str | None
    approved_at: datetime | None
    pending_change: dict[str, Any] | None
    drafted_by: str | None
    drafted_at: datetime | None

    @staticmethod
    def resolve_runnable(obj: Any) -> bool:
        return bool(obj.is_runnable())

    @staticmethod
    def resolve_approved_by(obj: Any) -> str | None:
        return obj.approved_by.username if obj.approved_by else None

    @staticmethod
    def resolve_drafted_by(obj: Any) -> str | None:
        return obj.drafted_by.username if obj.drafted_by else None


class RunbookExecutionOut(Schema):
    id: uuid.UUID
    runbook_id: str
    runbook_title: str
    executor: str
    state: str
    attempt: int
    payload: dict[str, Any]
    executed_payload: dict[str, Any]
    executed_by: str
    approved_by: str | None
    second_approver: str | None
    external_ref: str
    error: str
    result: dict[str, Any]
    executed_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    awaiting_until: datetime | None
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str

    @staticmethod
    def resolve_runbook_id(obj: Any) -> str:
        return str(obj.runbook_code)

    @staticmethod
    def resolve_runbook_title(obj: Any) -> str:
        return obj.runbook.title if obj.runbook else obj.runbook_code

    @staticmethod
    def resolve_executed_by(obj: Any) -> str:
        return str(obj.executed_by.username)

    @staticmethod
    def resolve_approved_by(obj: Any) -> str | None:
        return obj.approved_by.username if obj.approved_by else None

    @staticmethod
    def resolve_second_approver(obj: Any) -> str | None:
        return obj.second_approver.username if obj.second_approver else None

    @staticmethod
    def resolve_resolved_by(obj: Any) -> str | None:
        return obj.resolved_by.username if obj.resolved_by else None


class RunbookPanelOut(Schema):
    runbook_id: str | None
    draft_payload: dict[str, Any]
    runbook: RunbookOut | None
    approved: bool
    executions: list[RunbookExecutionOut]
