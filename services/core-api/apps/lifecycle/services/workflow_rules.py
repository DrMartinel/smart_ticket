"""Changes to the workflow rules, each audited with a reason, and the preview of what they choose
(ADR-0055)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import connection, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.categories.models import Category
from apps.lifecycle.domain.errors import WorkflowRuleError
from apps.lifecycle.domain.selection import select_workflow
from apps.lifecycle.domain.vocabulary import RuleRefusal
from apps.lifecycle.models import Workflow, WorkflowRule
from apps.lifecycle.services.config import workflow_config
from apps.tickets.domain.router import Branch

_LOCK = "workflow_rules"


@dataclass(frozen=True)
class Preview:
    """The workflow the rules would choose for one set of keys, and what chose it."""

    workflow_id: uuid.UUID
    workflow_name: str
    selected_by: str
    rule_id: uuid.UUID | None


class WorkflowRules:
    """Adds, edits, reorders and deletes workflow rules, and previews what they choose."""

    def create(self, actor: User, data: dict[str, Any]) -> WorkflowRule:
        """Adds a rule after every other one."""
        reason = self.reason_of(data)
        with transaction.atomic():
            self.lock()
            rule = WorkflowRule(order=WorkflowRule.objects.next_order())
            self.apply(rule, data)
            rule.changed_by = actor
            rule.change_reason = reason
            rule.save()
            self.audit("workflow_rule_created", actor, reason, rule, after=self.snapshot(rule))
        return self.reloaded(rule)

    def edit(self, actor: User, rule_id: uuid.UUID, data: dict[str, Any]) -> WorkflowRule:
        """Applies the given keys, workflow and `is_active`; a key sent as null matches any."""
        reason = self.reason_of(data)
        with transaction.atomic():
            rule = self.locked(rule_id)
            before = self.snapshot(rule)
            self.apply(rule, data)
            after = self.snapshot(rule)
            if after == before:
                return self.reloaded(rule)
            rule.changed_by = actor
            rule.change_reason = reason
            rule.save()
            self.audit("workflow_rule_changed", actor, reason, rule, before=before, after=after)
        return self.reloaded(rule)

    def reorder(self, actor: User, ids: list[uuid.UUID], reason: str) -> list[WorkflowRule]:
        """Gives the rules the order of `ids`, which names every rule once."""
        reason = self.reason_of({"reason": reason})
        with transaction.atomic():
            self.lock()
            rules = {r.id: r for r in WorkflowRule.objects.select_for_update()}
            if len(ids) != len(set(ids)) or set(ids) != set(rules):
                raise WorkflowRuleError(
                    422,
                    RuleRefusal.ORDER_INCOMPLETE,
                    "name every rule exactly once",
                    {"rule_count": len(rules)},
                )
            before = [str(r.id) for r in sorted(rules.values(), key=lambda r: r.order)]
            for order, rule_id in enumerate(ids, start=1):
                rules[rule_id].order = order
            WorkflowRule.objects.bulk_update(rules.values(), ["order"])
            AuditLog.objects.record(
                "workflow_rules_reordered",
                actor_type="human",
                actor_id=actor.id,
                payload={"reason": reason, "before": before, "after": [str(i) for i in ids]},
            )
        return list(WorkflowRule.objects.in_order())

    def delete(self, actor: User, rule_id: uuid.UUID, reason: str) -> None:
        """Deletes a rule."""
        reason = self.reason_of({"reason": reason})
        with transaction.atomic():
            rule = self.locked(rule_id)
            self.audit("workflow_rule_deleted", actor, reason, rule, before=self.snapshot(rule))
            rule.delete()

    def preview(
        self,
        category: str | None,
        branch: str | None,
        priority: str | None,
        *,
        include_inactive: bool,
    ) -> Preview:
        """The workflow a ticket handed off with these keys would enter now."""
        category_workflow = Category.objects.workflow_of(category)
        selection = select_workflow(
            WorkflowRule.objects.all(),
            category,
            branch,
            priority,
            category_workflow=category_workflow.id if category_workflow else None,
            default_workflow=Workflow.objects.default().id,
            include_inactive=include_inactive,
        )
        return Preview(
            workflow_id=selection.workflow_id,
            workflow_name=Workflow.objects.get(pk=selection.workflow_id).name,
            selected_by=selection.selected_by,
            rule_id=selection.rule.id if selection.rule else None,
        )

    # ── checks ──

    def apply(self, rule: WorkflowRule, data: dict[str, Any]) -> None:
        """Sets the fields `data` carries on `rule`, refusing any the checks reject."""
        if "category" in data:
            rule.category_id = self.category(data["category"])
        if "branch" in data:
            rule.branch = self.branch(data["branch"])
        if "priority" in data:
            rule.priority = data["priority"]
        if data.get("workflow_id") is not None:
            rule.workflow = self.workflow(data["workflow_id"])
        if data.get("is_active") is not None:
            rule.is_active = data["is_active"]

    def category(self, slug: str | None) -> str | None:
        """`slug` if it names an active category; refuses one that is unknown or inactive."""
        if slug is None:
            return None
        if not Category.objects.active().filter(slug=slug).exists():
            raise WorkflowRuleError(
                422, RuleRefusal.UNKNOWN_CATEGORY, f"no active category {slug!r}"
            )
        return slug

    def branch(self, branch: str | None) -> str | None:
        """`branch`; refuses auto-reply, whose tickets are never handed off."""
        if branch == Branch.AUTO_REPLY.value:
            raise WorkflowRuleError(
                422,
                RuleRefusal.BRANCH_NEVER_HANDS_OFF,
                "an auto-replied ticket is never handed off",
            )
        return branch

    def workflow(self, workflow_id: uuid.UUID | str) -> Workflow:
        """The workflow `workflow_id` names; refuses one that doesn't exist and a strict one a
        handed-off ticket could be stuck in. The default workflow is allowed."""
        found = Workflow.objects.filter(pk=workflow_id).first()
        if found is None:
            raise WorkflowRuleError(
                422, RuleRefusal.WORKFLOW_NOT_FOUND, f"no workflow {str(workflow_id)!r}"
            )
        dead_ends = workflow_config.category_dead_ends(found)
        if dead_ends:
            raise WorkflowRuleError(
                422,
                RuleRefusal.WORKFLOW_HAS_NO_WAY_OUT,
                "a strict workflow needs a transition out of every status a handed-off ticket "
                "can be at",
                {"statuses": dead_ends},
            )
        return found

    def reason_of(self, data: dict[str, Any]) -> str:
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise WorkflowRuleError(
                422, RuleRefusal.REASON_REQUIRED, "say why the workflow rules change"
            )
        return reason

    # ── rows ──

    def lock(self) -> None:
        """Serialises the changes that give a rule its order."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [_LOCK])

    def locked(self, rule_id: uuid.UUID) -> WorkflowRule:
        rule = WorkflowRule.objects.select_for_update().filter(pk=rule_id).first()
        if rule is None:
            raise WorkflowRuleError(404, RuleRefusal.RULE_NOT_FOUND, f"no rule {rule_id}")
        return rule

    def reloaded(self, rule: WorkflowRule) -> WorkflowRule:
        return WorkflowRule.objects.in_order().get(pk=rule.pk)

    def snapshot(self, rule: WorkflowRule) -> dict[str, Any]:
        return {
            "order": rule.order,
            "category": rule.category_id,
            "branch": rule.branch,
            "priority": rule.priority,
            "workflow": str(rule.workflow_id),
            "is_active": rule.is_active,
        }

    def audit(
        self, event: str, actor: User, reason: str, rule: WorkflowRule, **change: Any
    ) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human",
            actor_id=actor.id,
            payload={"rule": str(rule.id), "reason": reason, **change},
        )


workflow_rules = WorkflowRules()
