"""The default workflow every installation starts with (ADR-0028, ADR-0040)."""

from __future__ import annotations

from typing import Any

# key, name, kind, color
DEFAULT_STATUSES = [
    ("new", "New", "backlog", "#6B7280"),
    ("awaiting_requester", "Awaiting requester", "backlog", "#9CA3AF"),
    ("pending_review", "Pending review", "active", "#3B82F6"),
    ("blocked", "Blocked", "active", "#EF4444"),
    ("escalated", "Escalated", "active", "#DC2626"),
    ("auto_routed", "Auto-routed", "active", "#0EA5E9"),
    ("reopened", "Reopened", "active", "#F97316"),
    ("in_progress", "In progress", "active", "#F59E0B"),
    ("on_hold", "On hold", "active", "#8B5CF6"),
    ("waiting_on_requester", "Waiting on requester", "active", "#A78BFA"),
    ("auto_replied", "Auto-replied", "completed", "#10B981"),
    ("resolved", "Resolved", "completed", "#22C55E"),
    ("closed", "Closed", "completed", "#64748B"),
]

DEFAULT_WORKFLOW = "Default"

# Statuses whose time doesn't count toward the SLA (F1, BR-F1-07).
PAUSES_SLA = frozenset({"waiting_on_requester"})


def seed_default_workflow(workflow: Any, workflow_status: Any) -> Any:
    """Creates whatever is missing of the default workflow, given the two model classes;
    returns the default workflow."""
    default = workflow.objects.filter(is_default=True).first()
    if default is not None:
        return default
    default, _ = workflow.objects.get_or_create(
        name=DEFAULT_WORKFLOW,
        defaults={
            "description": "The workflow every ticket starts in.",
            "transition_policy": "open",
        },
    )
    default.is_default = True
    default.save(update_fields=["is_default"])
    for order, (key, name, kind, color) in enumerate(DEFAULT_STATUSES, start=1):
        workflow_status.objects.get_or_create(
            workflow=default,
            key=key,
            defaults={
                "kind": kind,
                "name": name,
                "color": color,
                "order": order,
                "pauses_sla": key in PAUSES_SLA,
            },
        )
    return default
