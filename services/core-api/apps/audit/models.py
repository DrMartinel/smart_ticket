"""Append-only audit log — spec §3.5.

Application code never UPDATEs or DELETEs a row here (and, per
infra/migrations/sql/0004_grants_and_audit_lockdown.sql, the database
itself refuses UPDATE/DELETE for the app role too — this is not just a
convention).
"""

from __future__ import annotations

import uuid

from typing import Any, ClassVar

from django.db import models

from apps.core.models import BaseModel


class AuditLogManager(models.Manager["AuditLog"]):
    def record(
        self,
        event: str,
        *,
        actor_type: str,
        actor_id: uuid.UUID | None = None,
        ticket_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> AuditLog:
        """The one way anything in core-api writes an audit trail entry.

        Every span/log field the spec asks for (§11.2) — ticket_public_id,
        prompt_version, graph_version, thresholds_version, shadow_mode —
        should be present in `payload` for AI-related events.
        """
        return self.create(
            ticket_id=ticket_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event=event,
            payload=payload or {},
            trace_id=trace_id,
        )


class AuditLog(BaseModel):
    ticket_id = models.UUIDField(null=True, blank=True)
    actor_type = models.CharField(max_length=20)  # system|ai|human
    actor_id = models.UUIDField(null=True, blank=True)
    event = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=64, null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[AuditLogManager] = AuditLogManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    class Meta(BaseModel.Meta):
        db_table = "audit_log"
        # Indexes (idx_audit_ticket, idx_audit_trace) are created by
        # infra/migrations/sql/0002_indexes.sql, not here, to keep index
        # ownership in one place; apps/dbextras/migrations/0002_finalize.py
        # runs that file. No db_index=True on fields either — it would add a
        # second, duplicate index beside the SQL one.

    def __str__(self) -> str:
        return f"{self.event} @ {self.occurred_at}"
