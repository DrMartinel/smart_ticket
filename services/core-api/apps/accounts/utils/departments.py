"""The department tree, its heads, and placing people in it (F14, BR-F14-10, BR-F14-11, BR-F14-13)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Assignment, AssignmentSource, Department, User
from apps.accounts.utils.access import Access
from apps.accounts.utils.catalog import ScopeKind
from apps.accounts.utils.grants import grants, require_reason
from apps.accounts.utils.vocabulary import EndReason, OrgError, OrgRefusal
from apps.audit.models import AuditLog
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent

DEPARTMENT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,29}$")


@dataclass(frozen=True)
class DepartmentDraft:
    """A department's fields; None leaves a field as it is, "" clears the head."""

    name: str | None = None
    parent: str | None = None
    head: str | None = None
    cost_centre: str | None = None


class Departments:
    """Creates, edits, moves and archives departments, each audited with a reason."""

    def create(
        self, actor: User | None, code: str, draft: DepartmentDraft, reason: str
    ) -> Department:
        reason = require_reason(reason)
        code = code.strip().upper()
        if not DEPARTMENT_CODE.match(code):
            raise OrgError(
                422, OrgRefusal.DEPARTMENT_CODE_INVALID, "a code is capitals, digits and dashes"
            )
        if not (draft.name or "").strip():
            raise OrgError(422, OrgRefusal.DEPARTMENT_NAME_REQUIRED, "a department needs a name")
        with transaction.atomic():
            if Department.objects.filter(code=code).exists():
                raise OrgError(409, OrgRefusal.DEPARTMENT_CODE_TAKEN, f"{code} is taken")
            parent = self.live(draft.parent) if draft.parent else None
            self.check_depth(parent, 1)
            department = Department.objects.create(
                code=code,
                name=(draft.name or "").strip(),
                parent=parent,
                cost_centre=(draft.cost_centre or "").strip(),
            )
            if draft.head:
                self.set_head(actor, department, draft.head)
            self.audit(actor, department, "created", reason, None)
        return department

    def update(
        self, actor: User | None, code: str, draft: DepartmentDraft, reason: str
    ) -> Department:
        """Renames a department, sets its cost centre or head; `parent` goes through `move`."""
        reason = require_reason(reason)
        with transaction.atomic():
            department = self.live(code, lock=True)
            before = self.snapshot(department)
            if draft.name is not None and draft.name.strip():
                department.name = draft.name.strip()
            if draft.cost_centre is not None:
                department.cost_centre = draft.cost_centre.strip()
            department.save(update_fields=["name", "cost_centre"])
            if draft.head is not None:
                self.set_head(actor, department, draft.head)
            self.audit(actor, department, "updated", reason, before)
        return department

    def move(
        self, actor: User | None, code: str, parent_code: str | None, reason: str
    ) -> Department:
        """Puts a department under another, or at the top; never under itself (BR-F14-10)."""
        reason = require_reason(reason)
        with transaction.atomic():
            department = self.live(code, lock=True)
            before = self.snapshot(department)
            parent = self.live(parent_code) if parent_code else None
            if parent is not None and parent.id in self.subtree_ids(department):
                raise OrgError(
                    409, OrgRefusal.DEPARTMENT_CYCLE, f"{parent.code} is inside {department.code}"
                )
            self.check_depth(parent, self.height(department))
            department.parent = parent
            department.save(update_fields=["parent"])
            self.audit(actor, department, "moved", reason, before)
        return department

    def archive(self, actor: User | None, code: str, reason: str) -> Department:
        """Archives an empty department and ends the grants scoped to it."""
        reason = require_reason(reason)
        with transaction.atomic():
            department = self.live(code, lock=True)
            if department.is_default:
                raise OrgError(
                    409, OrgRefusal.DEPARTMENT_IS_DEFAULT, "the default department stays"
                )
            people = department.people.filter(is_active=True).count()
            children = department.children.filter(archived_at__isnull=True).count()
            if people or children:
                raise OrgError(
                    409,
                    OrgRefusal.DEPARTMENT_NOT_EMPTY,
                    f"{department.code} still has people or departments",
                    {"people": people, "departments": children},
                )
            before = self.snapshot(department)
            grants.set_department_head(actor, department, None)
            grants.end_rows(
                Assignment.objects.active().filter(scope_department=department),
                EndReason.DEPARTMENT_ARCHIVED,
                actor,
                reason,
            )
            department.head = None
            department.archived_at = timezone.now()
            department.save(update_fields=["head", "archived_at"])
            self.audit(actor, department, "archived", reason, before)
        return department

    def set_head(self, actor: User | None, department: Department, username: str) -> None:
        """Makes `username` the head, "" for nobody, and moves the structural grant with it."""
        head = None
        if username:
            head = User.objects.filter(username=username, is_active=True).first()
            if head is None:
                raise OrgError(404, OrgRefusal.USER_NOT_FOUND, f"no active user {username!r}")
            if actor is not None and head.pk == actor.pk and department.head_id != actor.pk:
                raise OrgError(403, OrgRefusal.OWN_RIGHTS, "another person makes you a head")
        department.head = head
        department.save(update_fields=["head"])
        grants.set_department_head(actor, department, head)

    # ── people ──

    def place(
        self,
        actor: User | None,
        user: User,
        department: Department,
        reason: str,
    ) -> bool:
        """Moves `user` into `department`, flagging their department-scoped grants for review
        (BR-F14-13); False when they were already there."""
        if user.department_id == department.id:
            return False
        previous = user.department
        user.department = department
        user.save(update_fields=["department"])
        if previous is not None:
            due = timezone.now() + timedelta(days=settings.THRESHOLDS.access.mover_review_days)
            Assignment.objects.active().filter(
                user=user, scope_kind=ScopeKind.DEPARTMENT.value
            ).exclude(source=AssignmentSource.STRUCTURAL.value).update(
                needs_review=True, review_due_at=due
            )
        Access.forget(user)
        AuditLog.objects.record(
            "person_moved",
            actor_type="human" if actor else "system",
            actor_id=actor.id if actor else None,
            payload={
                "user": user.username,
                "from": previous.code if previous else None,
                "to": department.code,
                "reason": reason,
            },
        )
        if previous is not None:
            notifier.emit(
                NotificationEvent.ORG_PERSON_MOVED,
                None,
                Notice(
                    actor=actor.username if actor else "system",
                    reason=reason,
                    detail=department.name,
                    subjects=(user,),
                    data={"from": previous.code, "to": department.code},
                ),
            )
        return True

    # ── the tree ──

    def check_depth(self, parent: Department | None, height: int) -> None:
        """Refuses a subtree of `height` levels under `parent` deeper than the threshold."""
        limit = settings.THRESHOLDS.access.department_max_depth
        depth = self.depth(parent) + height if parent else height
        if depth > limit:
            raise OrgError(
                422,
                OrgRefusal.DEPARTMENT_TOO_DEEP,
                f"the tree would be {depth} levels deep; the limit is {limit}",
            )

    def depth(self, department: Department) -> int:
        """Levels from the top down to `department`, the top counted as 1."""
        levels, parent_id = 1, department.parent_id
        parents = dict(Department.objects.values_list("id", "parent_id"))
        while parent_id is not None:
            levels += 1
            parent_id = parents.get(parent_id)
        return levels

    def height(self, department: Department) -> int:
        """Levels from `department` down to its deepest live descendant, itself counted."""
        children: dict[uuid.UUID, list[uuid.UUID]] = {}
        for dept_id, parent_id in Department.objects.live().values_list("id", "parent_id"):
            if parent_id is not None:
                children.setdefault(parent_id, []).append(dept_id)

        def below(dept_id: uuid.UUID) -> int:
            return 1 + max((below(c) for c in children.get(dept_id, [])), default=0)

        return below(department.id)

    def subtree_ids(self, department: Department) -> set[uuid.UUID]:
        children: dict[uuid.UUID, list[uuid.UUID]] = {}
        for dept_id, parent_id in Department.objects.values_list("id", "parent_id"):
            if parent_id is not None:
                children.setdefault(parent_id, []).append(dept_id)
        found, todo = set(), [department.id]
        while todo:
            current = todo.pop()
            found.add(current)
            todo.extend(children.get(current, []))
        return found

    def live(self, code: str | None, *, lock: bool = False) -> Department:
        rows = Department.objects.select_for_update() if lock else Department.objects.all()
        department = rows.filter(code=(code or "").strip().upper()).first()
        if department is None:
            raise OrgError(404, OrgRefusal.DEPARTMENT_NOT_FOUND, f"no department {code!r}")
        if department.archived_at is not None:
            raise OrgError(409, OrgRefusal.DEPARTMENT_ARCHIVED, f"{department.code} is archived")
        return department

    def default(self) -> Department:
        return Department.objects.get(is_default=True)

    def snapshot(self, department: Department) -> dict[str, Any]:
        return {
            "code": department.code,
            "name": department.name,
            "parent": department.parent.code if department.parent else None,
            "head": department.head.username if department.head else None,
            "cost_centre": department.cost_centre,
        }

    def audit(
        self,
        actor: User | None,
        department: Department,
        change: str,
        reason: str,
        before: dict[str, Any] | None,
    ) -> None:
        AuditLog.objects.record(
            "department_changed",
            actor_type="human" if actor else "system",
            actor_id=actor.id if actor else None,
            payload={
                "change": change,
                "department": department.code,
                "before": before,
                "after": self.snapshot(department),
                "reason": reason,
            },
        )


# --- the departments service ---

departments = Departments()
