"""The system statuses and default workflow every installation starts with (ADR-0028)."""

from __future__ import annotations

from typing import Any

# name, color, order, is_backlog, is_completed
SYSTEM_STATUSES = [
    ("Intake", "#6B7280", 1, True, False),
    ("Open", "#3B82F6", 2, False, False),
    ("In progress", "#F59E0B", 3, False, False),
    ("On hold", "#8B5CF6", 4, False, False),
    ("Resolved", "#22C55E", 5, False, True),
    ("Closed", "#64748B", 6, False, True),
]

# key, name, system status, color
DEFAULT_STATUSES = [
    ("new", "New", "Intake", "#6B7280"),
    ("awaiting_requester", "Awaiting requester", "Intake", "#9CA3AF"),
    ("pending_review", "Pending review", "Open", "#3B82F6"),
    ("blocked", "Blocked", "Open", "#EF4444"),
    ("escalated", "Escalated", "Open", "#DC2626"),
    ("auto_routed", "Auto-routed", "Open", "#0EA5E9"),
    ("reopened", "Reopened", "Open", "#F97316"),
    ("in_progress", "In progress", "In progress", "#F59E0B"),
    ("on_hold", "On hold", "On hold", "#8B5CF6"),
    ("waiting_on_requester", "Waiting on requester", "On hold", "#A78BFA"),
    ("auto_replied", "Auto-replied", "Resolved", "#10B981"),
    ("resolved", "Resolved", "Resolved", "#22C55E"),
    ("closed", "Closed", "Closed", "#64748B"),
]

DEFAULT_WORKFLOW = "Default"

# Statuses whose time doesn't count toward the SLA (F1, BR-F1-07).
PAUSES_SLA = frozenset({"waiting_on_requester"})


def seed_default_workflow(system_status: Any, workflow: Any, workflow_status: Any) -> Any:
    """Creates whatever is missing of the seed, given the three model classes; returns the
    default workflow."""
    bases = {}
    for name, color, order, is_backlog, is_completed in SYSTEM_STATUSES:
        bases[name], _ = system_status.objects.get_or_create(
            name=name,
            defaults={
                "color": color,
                "order": order,
                "is_backlog": is_backlog,
                "is_completed": is_completed,
            },
        )
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
    # Migrations before lifecycle 0004 pass a model without `pauses_sla`.
    has_pause = any(f.name == "pauses_sla" for f in workflow_status._meta.get_fields())
    for order, (key, name, base, color) in enumerate(DEFAULT_STATUSES, start=1):
        defaults = {"base": bases[base], "name": name, "color": color, "order": order}
        if has_pause:
            defaults["pauses_sla"] = key in PAUSES_SLA
        workflow_status.objects.get_or_create(workflow=default, key=key, defaults=defaults)
    return default
