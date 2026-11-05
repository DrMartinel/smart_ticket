"""Granting and ending roles at a scope, and the grants structure keeps in step (F14, ADR-0045)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import (
    Assignment,
    AssignmentSource,
    Department,
    Role,
    User,
    UserRole,
)
from apps.accounts.utils import sessions
from apps.accounts.utils.access import Access, holders, role_permissions, role_scopes
from apps.accounts.utils.catalog import (
    BASE_ROLES,
    PERMISSIONS,
    STRUCTURAL_ROLES,
    Permission,
    ScopeKind,
    SystemRole,
)
from apps.accounts.utils.vocabulary import EndReason, OrgError, OrgRefusal
from apps.audit.models import AuditLog
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent

if TYPE_CHECKING:
    from apps.teams.models import Team


@dataclass(frozen=True)
class GrantRequest:
    """A role for a person at a scope, from `starts_at` until `ends_at` when given."""

    username: str
    role_urn: str
    scope_kind: ScopeKind
    scope_ref: str | None
    reason: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None


@dataclass(frozen=True)
class Target:
    """Where a grant applies: everywhere, one team, or one department and its subtree."""

    kind: ScopeKind
    team: Team | None = None
    department: Department | None = None


class Grants:
    """Every change to who holds which role where, each audited and ending the person's sign-ins."""

    def grant(self, actor: User, request: GrantRequest) -> Assignment:
        """Gives `request.username` the role at the scope, refusing anything the actor couldn't hold."""
        reason = require_reason(request.reason)
        with transaction.atomic():
            user = locked_user(request.username)
            role = live_role(request.role_urn)
            target = self.target(request.scope_kind, request.scope_ref)
            self.check_grantable(actor, user, role, target)
            starts_at = request.starts_at or timezone.now()
            if request.ends_at is not None and request.ends_at <= max(starts_at, timezone.now()):
                raise OrgError(422, OrgRefusal.ENDS_BEFORE_START, "the grant must end later")
            if self.same_grants(user, role, target).exists():
                raise OrgError(
                    409, OrgRefusal.GRANT_EXISTS, f"{user.username} already holds {role.urn} there"
                )
            row = Assignment.objects.create(
                user=user,
                role=role,
                scope_kind=target.kind.value,
                scope_team=target.team,
                scope_department=target.department,
                source=AssignmentSource.MANUAL.value,
                granted_by=actor,
                reason=reason,
                starts_at=starts_at,
                ends_at=request.ends_at,
            )
            self.changed(actor, row, "granted", reason)
            notifier.emit(
                NotificationEvent.ACCESS_GRANTED,
                None,
                Notice(
                    actor=actor.username,
                    reason=reason,
                    detail=f"{role.name} ({row.scope_label()})",
                    link="/me",
                    subjects=(user,),
                    data={"role": role.urn, "scope": row.scope_label()},
                ),
            )
        return row

    def end(self, actor: User, assignment_id: uuid.UUID, reason: str) -> Assignment:
        """Ends a grant now; a structural grant ends only with the structure behind it."""
        reason = require_reason(reason)
        with transaction.atomic():
            row = self.locked(assignment_id)
            if row.source == AssignmentSource.STRUCTURAL.value:
                raise OrgError(
                    409,
                    OrgRefusal.GRANT_IS_STRUCTURAL,
                    "change the team lead or department head instead",
                )
            self.check_grantable(actor, row.user, row.role, self.target_of(row), ending=True)
            self.end_rows(Assignment.objects.filter(pk=row.pk), EndReason.ENDED, actor, reason)
            row.refresh_from_db()
        return row

    def extend(
        self, actor: User, assignment_id: uuid.UUID, ends_at: datetime | None, reason: str
    ) -> Assignment:
        """Sets or clears a grant's end date."""
        reason = require_reason(reason)
        with transaction.atomic():
            row = self.locked(assignment_id)
            self.check_grantable(actor, row.user, row.role, self.target_of(row), ending=True)
            if ends_at is not None and ends_at <= max(row.starts_at, timezone.now()):
                raise OrgError(422, OrgRefusal.ENDS_BEFORE_START, "the grant must end later")
            row.ends_at = ends_at
            row.expiry_noticed_at = None
            row.save(update_fields=["ends_at", "expiry_noticed_at"])
            self.changed(actor, row, "end_date_set", reason)
        return row

    def confirm(self, actor: User, assignment_id: uuid.UUID, reason: str) -> Assignment:
        """Keeps a grant flagged for review, e.g. a mover's old department grant."""
        reason = require_reason(reason)
        with transaction.atomic():
            row = self.locked(assignment_id)
            self.check_grantable(actor, row.user, row.role, self.target_of(row), ending=True)
            row.needs_review = False
            row.review_due_at = None
            row.reviewed_at = timezone.now()
            row.save(update_fields=["needs_review", "review_due_at", "reviewed_at"])
            self.changed(actor, row, "confirmed", reason)
        return row

    # ── the rules ──

    def check_grantable(
        self, actor: User, user: User, role: Role, target: Target, *, ending: bool = False
    ) -> None:
        """Never your own grants, no base or structural role by hand, staff-only roles for
        staff, a scope the role allows; a system role from an access admin, a custom role only
        with permissions the actor holds there (BR-F14-05)."""
        if user.pk == actor.pk:
            raise OrgError(403, OrgRefusal.OWN_RIGHTS, "another person changes your access")
        if role.is_system and SystemRole(role.urn) in BASE_ROLES.values():
            raise OrgError(
                422, OrgRefusal.ROLE_IS_BASE, "a base role is set on the person, not granted"
            )
        if not ending and role.is_system and SystemRole(role.urn) in STRUCTURAL_ROLES:
            raise OrgError(
                422,
                OrgRefusal.ROLE_IS_STRUCTURAL,
                "team leads and department heads follow the team or department",
            )
        permissions = role_permissions(role)
        if not ending:
            if not user.is_active:
                raise OrgError(409, OrgRefusal.USER_INACTIVE, f"{user.username} is not active")
            if user.role == UserRole.EMPLOYEE.value and any(
                PERMISSIONS[p].staff_only for p in permissions
            ):
                raise OrgError(
                    422, OrgRefusal.STAFF_ONLY, "an employee holds no staff role (BR-F14-06)"
                )
            if target.kind not in role_scopes(permissions):
                raise OrgError(
                    422,
                    OrgRefusal.SCOPE_NOT_ALLOWED,
                    f"{role.urn} can't be granted at {target.kind.value} scope",
                    {"allowed": [s.value for s in role_scopes(permissions)]},
                )
        access = Access.of(actor)
        if role.is_system:
            if not access.holds_everywhere(Permission.ACCESS_GRANT):
                raise OrgError(
                    403,
                    OrgRefusal.CANNOT_GRANT_UNHELD,
                    "a system role is granted by an access admin",
                    {"permissions": [Permission.ACCESS_GRANT.value]},
                )
            return
        unheld = sorted(p.value for p in permissions if not self.covers(access, p, target))
        if unheld:
            raise OrgError(
                403,
                OrgRefusal.CANNOT_GRANT_UNHELD,
                "you can only grant what you hold over that scope",
                {"permissions": unheld},
            )

    def covers(self, access: Access, permission: Permission, target: Target) -> bool:
        scope = access.scope(permission)
        if scope is None:
            return False
        if scope.everywhere:
            return True
        if target.team is not None:
            return target.team.id in scope.team_ids
        if target.department is not None:
            return target.department.id in scope.department_ids
        return False

    def check_not_last_admin(self, user: User) -> None:
        """Refuses to take the last access admin who isn't a break-glass account (BR-F14-08)."""
        if user.is_break_glass or not Access.of(user).holds(Permission.ACCESS_GRANT):
            return
        others = [
            person
            for person, _ in holders(Permission.ACCESS_GRANT)
            if person.pk != user.pk and not person.is_break_glass
        ]
        if not others:
            raise OrgError(
                409,
                OrgRefusal.LAST_ACCESS_ADMIN,
                f"{user.username} is the last person who can grant access",
            )

    # ── structure ──

    def set_team_lead(self, actor: User | None, team: Team, user: User, *, lead: bool) -> None:
        """Gives or ends the team-scoped team-lead grant to match the membership."""
        role = Role.objects.get(urn=SystemRole.TEAM_LEAD.value)
        target = Target(ScopeKind.TEAM, team=team)
        held = self.same_grants(user, role, target)
        if lead and not held.exists():
            row = Assignment.objects.create(
                user=user,
                role=role,
                scope_kind=ScopeKind.TEAM.value,
                scope_team=team,
                source=AssignmentSource.STRUCTURAL.value,
                granted_by=actor,
                reason=f"leads team {team.slug}",
            )
            self.changed(actor, row, "granted", row.reason)
        elif not lead:
            self.end_rows(held, EndReason.NO_LONGER_LEAD, actor, f"no longer leads {team.slug}")

    def set_department_head(
        self, actor: User | None, department: Department, head: User | None
    ) -> None:
        """Moves the department-head grant on `department` to `head`, or ends it."""
        role = Role.objects.get(urn=SystemRole.DEPARTMENT_HEAD.value)
        rows = Assignment.objects.active().filter(
            role=role, scope_kind=ScopeKind.DEPARTMENT.value, scope_department=department
        )
        self.end_rows(
            rows.exclude(user=head) if head else rows,
            EndReason.NO_LONGER_HEAD,
            actor,
            f"no longer heads {department.code}",
        )
        if head is not None and not rows.filter(user=head).exists():
            row = Assignment.objects.create(
                user=head,
                role=role,
                scope_kind=ScopeKind.DEPARTMENT.value,
                scope_department=department,
                source=AssignmentSource.STRUCTURAL.value,
                granted_by=actor,
                reason=f"heads {department.code}",
            )
            self.changed(actor, row, "granted", row.reason)

    # ── the sweep ──

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Ends expired and unconfirmed mover grants, and tells people whose grants end soon."""
        now = now or timezone.now()
        access = settings.THRESHOLDS.access
        expired = self.end_rows(
            Assignment.objects.filter(ended_at__isnull=True, ends_at__lte=now),
            EndReason.EXPIRED,
            None,
            "the grant's end date passed",
        )
        unconfirmed = self.end_rows(
            Assignment.objects.active(now).filter(needs_review=True, review_due_at__lte=now),
            EndReason.MOVER_UNCONFIRMED,
            None,
            "not confirmed after the person moved",
        )
        soon = Assignment.objects.active(now).filter(
            ends_at__lte=now + timedelta(hours=access.expiry_notice_hours),
            expiry_noticed_at__isnull=True,
        )
        noticed = 0
        for row in soon.select_related(
            "user", "role", "granted_by", "scope_team", "scope_department"
        ):
            people = tuple(p for p in (row.user, row.granted_by) if p is not None)
            assert row.ends_at is not None
            notifier.emit(
                NotificationEvent.ACCESS_GRANT_EXPIRING,
                None,
                Notice(
                    detail=f"{row.role.name} ({row.scope_label()})",
                    message=f"{row.user.username}'s grant ends {row.ends_at.isoformat()}",
                    link="/me",
                    subjects=people,
                    data={"assignment": str(row.id), "ends_at": row.ends_at.isoformat()},
                ),
            )
            Assignment.objects.filter(pk=row.pk).update(expiry_noticed_at=now)
            noticed += 1
        return {"expired": expired, "unconfirmed": unconfirmed, "noticed": noticed}

    # ── the writes every change shares ──

    def end_rows(
        self, rows: QuerySet[Assignment], why: EndReason, actor: User | None, reason: str
    ) -> int:
        """Ends `rows`, audits each, and ends the sign-ins of everyone who lost access."""
        ended = list(rows.filter(ended_at__isnull=True).select_related("user", "role"))
        if not ended:
            return 0
        now = timezone.now()
        Assignment.objects.filter(pk__in=[r.pk for r in ended]).update(
            ended_at=now, ended_reason=why.value
        )
        for row in ended:
            row.ended_at, row.ended_reason = now, why.value
            self.changed(actor, row, f"ended:{why.value}", reason, revoke=False)
        for user in {row.user_id: row.user for row in ended}.values():
            Access.forget(user)
            sessions.revoke_user(user, "rights_changed")
        return len(ended)

    def changed(
        self, actor: User | None, row: Assignment, change: str, reason: str, *, revoke: bool = True
    ) -> None:
        AuditLog.objects.record(
            "grant_changed",
            actor_type="human" if actor else "system",
            actor_id=actor.id if actor else None,
            payload={
                "change": change,
                "user": row.user.username,
                "role": row.role.urn,
                "scope": row.scope_label(),
                "assignment": str(row.id),
                "source": row.source,
                "ends_at": row.ends_at.isoformat() if row.ends_at else None,
                "reason": reason,
            },
        )
        if revoke:
            Access.forget(row.user)
            sessions.revoke_user(row.user, "rights_changed")

    # ── lookups ──

    def target(self, kind: ScopeKind, ref: str | None) -> Target:
        """The team or department a scope names; refuses one that doesn't exist."""
        from apps.teams.models import Team

        if kind is ScopeKind.GLOBAL:
            return Target(kind)
        if kind is ScopeKind.TEAM:
            team = Team.objects.filter(slug=ref or "", is_active=True).first()
            if team is None:
                raise OrgError(404, OrgRefusal.SCOPE_TARGET_NOT_FOUND, f"no active team {ref!r}")
            return Target(kind, team=team)
        department = Department.objects.live().filter(code=ref or "").first()
        if department is None:
            raise OrgError(404, OrgRefusal.SCOPE_TARGET_NOT_FOUND, f"no department {ref!r}")
        return Target(kind, department=department)

    def target_of(self, row: Assignment) -> Target:
        return Target(ScopeKind(row.scope_kind), row.scope_team, row.scope_department)

    def same_grants(self, user: User, role: Role, target: Target) -> QuerySet[Assignment]:
        return Assignment.objects.active().filter(
            user=user,
            role=role,
            scope_kind=target.kind.value,
            scope_team=target.team,
            scope_department=target.department,
        )

    def locked(self, assignment_id: uuid.UUID) -> Assignment:
        row = (
            Assignment.objects.select_for_update(of=("self",))
            .select_related("user", "role", "scope_team", "scope_department")
            .filter(pk=assignment_id)
            .first()
        )
        if row is None:
            raise OrgError(404, OrgRefusal.GRANT_NOT_FOUND, "no such grant")
        now = timezone.now()
        if row.ended_at is not None or (row.ends_at is not None and row.ends_at <= now):
            raise OrgError(409, OrgRefusal.GRANT_ENDED, "the grant has already ended")
        return row


def require_reason(reason: str) -> str:
    """The trimmed reason; refuses an empty one."""
    if not (reason or "").strip():
        raise OrgError(422, OrgRefusal.REASON_REQUIRED, "say why")
    return reason.strip()


def locked_user(username: str) -> User:
    user = User.objects.select_for_update().filter(username=username).first()
    if user is None:
        raise OrgError(404, OrgRefusal.USER_NOT_FOUND, f"no user {username!r}")
    return user


def live_role(urn: str) -> Role:
    role = Role.objects.filter(urn=urn).first()
    if role is None:
        raise OrgError(404, OrgRefusal.ROLE_NOT_FOUND, f"no role {urn!r}")
    if role.retired_at is not None:
        raise OrgError(409, OrgRefusal.ROLE_RETIRED, f"{urn} is retired")
    return role


def explain(user: User, permission: Permission) -> list[dict[str, Any]]:
    """The grants that give `user` `permission`, from the evaluator the gates use (BR-F14-17)."""
    return [vars(source) for source in Access.of(user).sources.get(permission, [])]


# --- the grants service ---

grants = Grants()
