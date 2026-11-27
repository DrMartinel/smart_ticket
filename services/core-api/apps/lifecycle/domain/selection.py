"""Chooses the workflow a ticket enters at handoff (ADR-0055). Pure."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from apps.lifecycle.domain.vocabulary import Fallback
from apps.lifecycle.models import WorkflowRule


@dataclass(frozen=True)
class Selection:
    """The workflow chosen, and the rule or fallback that chose it."""

    workflow_id: uuid.UUID
    # The rule's id, or `category` or `default`.
    selected_by: str
    rule: WorkflowRule | None = None


def select_workflow(
    rules: Iterable[WorkflowRule],
    category: str | None,
    branch: str | None,
    priority: str | None,
    *,
    category_workflow: uuid.UUID | None,
    default_workflow: uuid.UUID,
) -> Selection:
    """The first active rule in order that matches; else the category's workflow; else the
    default one."""
    for rule in sorted(rules, key=lambda r: r.order):
        if rule.is_active and rule.matches(category, branch, priority):
            return Selection(rule.workflow_id, str(rule.id), rule)
    if category_workflow is not None:
        return Selection(category_workflow, Fallback.CATEGORY.value)
    return Selection(default_workflow, Fallback.DEFAULT.value)
