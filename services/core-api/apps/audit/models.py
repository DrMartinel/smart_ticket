"""Append-only audit log — spec §3.5.

Application code never UPDATEs or DELETEs a row here (and, per
infra/migrations/sql/0004_grants_and_audit_lockdown.sql, the database
itself refuses UPDATE/DELETE for the app role too — this is not just a
convention).
"""

from django.db import models


class AuditLog(models.Model):
    ticket_id = models.BigIntegerField(null=True, blank=True)
    actor_type = models.CharField(max_length=20)  # system|ai|human
    actor_id = models.BigIntegerField(null=True, blank=True)
    event = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        # Indexes are created by infra/migrations/sql/0002_indexes.sql, not
        # here, to keep index ownership in one place (see apps/tickets's
        # migration 0002 which runs that file).

    def __str__(self) -> str:
        return f"{self.event} @ {self.occurred_at}"
