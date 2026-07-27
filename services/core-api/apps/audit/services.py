"""
`audit()` is the one function anything in core-api calls to write an audit
trail entry. Every span/log line the spec asks for (§11.2) — ticket_public_id,
prompt_version, graph_version, thresholds_version, shadow_mode — should be
present in `payload` for AI-related events.
"""

from __future__ import annotations

from typing import Any

from apps.audit.models import AuditLog


def audit(
    event: str,
    *,
    actor_type: str,
    actor_id: int | None = None,
    ticket_id: int | None = None,
    payload: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        ticket_id=ticket_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event=event,
        payload=payload or {},
        trace_id=trace_id,
    )
