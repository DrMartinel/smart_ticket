"""What a person may do and where: the one evaluator every gate and explanation reads (ADR-0045)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Assignment, Department, Role, RolePermission, User, UserRole
from apps.accounts.utils.catalog import (
    BASE_ROLES,
    PERMISSIONS,
    SYSTEM_ROLE_NAMES,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    ScopeKind,
    SystemRole,
)

if TYPE_CHECKING:
    from apps.tickets.models import Ticket

_CACHE = "_f14_access"


@dataclass(frozen=True)
class Scope:
    """Where a permission applies: everywhere, or some teams and department subtrees."""

    everywhere: bool = False
    team_ids: frozenset[uuid.UUID] = frozenset()
    department_ids: frozenset[uuid.UUID] = frozenset()

    def merged(self, other: Scope) -> Scope:
        return Scope(
            self.everywhere or other.everywhere,
            self.team_ids | other.team_ids,
            self.department_ids | other.department_ids,
        )

    def covers(self, *, team_id: uuid.UUID | None, department_id: uuid.UUID | None) -> bool:
        if self.everywhere:
            return True
        return (team_id is not None and team_id in self.team_ids) or (
            department_id is not None and department_id in self.department_ids
        )


@dataclass(frozen=True)
class Source:
    """One reason a person holds a permission: a role at a scope, from a grant or their base role."""

    role_urn: str
    role_name: str
    scope: str
    assignment_id: uuid.UUID | None
    granted_by: str | None
    granted_at: str | None
    ends_at: str | None


@dataclass
class Access:
    """A person's permissions and where each applies."""

    user: User
    scopes: dict[Permission, Scope] = field(default_factory=dict)
    sources: dict[Permission, list[Source]] = field(default_factory=dict)

    @classmethod
    def of(cls, user: User) -> Access:
        """The person's access, built once per user object."""
        cached = user.__dict__.get(_CACHE)
        if cached is None:
            cached = cls.build(user)
            user.__dict__[_CACHE] = cached
        return cached

    @staticmethod
    def forget(user: User) -> None:
        """Drops the cached access so the next check reads the grants again."""
        user.__dict__.pop(_CACHE, None)

    @classmethod
    def build(cls, user: User) -> Access:
        access = cls(user)
        base = BASE_ROLES[UserRole(user.role)]
        for permission in SYSTEM_ROLE_PERMISSIONS[base]:
            access.add(
                permission,
                Scope(everywhere=True),
                Source(base.value, SYSTEM_ROLE_NAMES[base], "global", None, None, None, None),
            )
        rows = list(
            Assignment.objects.active(timezone.now())
            .filter(user_id=user.pk, role__retired_at__isnull=True)
            .select_related("role", "scope_team", "scope_department", "granted_by")
        )
        if not rows:
            return access
        custom = custom_permissions({row.role_id for row in rows if not row.role.is_system})
        subtrees = (
            department_subtrees() if any(r.scope_kind == ScopeKind.DEPARTMENT for r in rows) else {}
        )
        staff = user.role != UserRole.EMPLOYEE.value
        for row in rows:
            scope = scope_of(row, subtrees)
            source = Source(
                row.role.urn,
                row.role.name,
                row.scope_label(),
                row.id,
                row.granted_by.username if row.granted_by else None,
                row.starts_at.isoformat(),
                row.ends_at.isoformat() if row.ends_at else None,
            )
            held = (
                SYSTEM_ROLE_PERMISSIONS.get(SystemRole(row.role.urn), frozenset())
                if row.role.is_system
                else custom.get(row.role_id, frozenset())
            )
            for permission in held:
                spec = PERMISSIONS[permission]
                if spec.staff_only and not staff:
                    continue
                if ScopeKind(row.scope_kind) not in spec.scopes:
                    continue
                access.add(permission, scope, source)
        return access

    def add(self, permission: Permission, scope: Scope, source: Source) -> None:
        held = self.scopes.get(permission)
        self.scopes[permission] = scope if held is None else held.merged(scope)
        self.sources.setdefault(permission, []).append(source)

    def holds(self, permission: Permission) -> bool:
        """Whether the person holds `permission` anywhere."""
        return permission in self.scopes

    def holds_everywhere(self, permission: Permission) -> bool:
        scope = self.scopes.get(permission)
        return scope is not None and scope.everywhere

    def scope(self, permission: Permission) -> Scope | None:
        return self.scopes.get(permission)

    def permissions(self) -> list[str]:
        return sorted(p.value for p in self.scopes)

    def covers_team(self, permission: Permission, team_id: uuid.UUID | None) -> bool:
        """Whether `permission` reaches the team `team_id`."""
        scope = self.scopes.get(permission)
        return scope is not None and scope.covers(team_id=team_id, department_id=None)

    def covers_ticket(self, permission: Permission, ticket: Ticket) -> bool:
        """Whether `permission` reaches `ticket` by its team or its requester's department."""
        scope = self.scopes.get(permission)
        if scope is None:
            return False
        if scope.everywhere:
            return True
        requester = ticket.reporter
        return scope.covers(
            team_id=ticket.team_id, department_id=requester.department_id if requester else None
        )

    def ticket_filter(self, permission: Permission, prefix: str = "") -> Q | None:
        """The tickets `permission` reaches as a filter; None for every ticket."""
        scope = self.scopes.get(permission)
        if scope is None:
            return Q(pk__in=[])
        if scope.everywhere:
            return None
        return Q(**{f"{prefix}team_id__in": scope.team_ids}) | Q(
            **{f"{prefix}reporter__department_id__in": scope.department_ids}
        )

    def team_ids(self, permission: Permission) -> frozenset[uuid.UUID] | None:
        """The teams `permission` reaches; None for every team."""
        scope = self.scopes.get(permission)
        if scope is None:
            return frozenset()
        return None if scope.everywhere else scope.team_ids

    def department_ids(self, permission: Permission) -> frozenset[uuid.UUID] | None:
        """The departments `permission` reaches, subtrees expanded; None for every department."""
        scope = self.scopes.get(permission)
        if scope is None:
            return frozenset()
        return None if scope.everywhere else scope.department_ids


def custom_permissions(role_ids: set[uuid.UUID]) -> dict[uuid.UUID, frozenset[Permission]]:
    """Each custom role's permissions that the catalogue still knows."""
    known = {p.value: p for p in Permission}
    found: dict[uuid.UUID, set[Permission]] = {}
    if role_ids:
        for role_id, urn in RolePermission.objects.filter(role_id__in=role_ids).values_list(
            "role_id", "permission_urn"
        ):
            if urn in known:
                found.setdefault(role_id, set()).add(known[urn])
    return {role_id: frozenset(perms) for role_id, perms in found.items()}


def department_subtrees() -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    """Each department with every department under it, itself included."""
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for dept_id, parent_id in Department.objects.values_list("id", "parent_id"):
        children.setdefault(parent_id, []).append(dept_id)
    subtrees: dict[uuid.UUID, frozenset[uuid.UUID]] = {}

    def walk(dept_id: uuid.UUID) -> frozenset[uuid.UUID]:
        if dept_id not in subtrees:
            below: set[uuid.UUID] = {dept_id}
            for child in children.get(dept_id, []):
                below |= walk(child)
            subtrees[dept_id] = frozenset(below)
        return subtrees[dept_id]

    for dept_ids in children.values():
        for dept_id in dept_ids:
            walk(dept_id)
    return subtrees


def scope_of(row: Assignment, subtrees: dict[uuid.UUID, frozenset[uuid.UUID]]) -> Scope:
    if row.scope_kind == ScopeKind.TEAM and row.scope_team_id:
        return Scope(team_ids=frozenset({row.scope_team_id}))
    if row.scope_kind == ScopeKind.DEPARTMENT and row.scope_department_id:
        return Scope(
            department_ids=subtrees.get(
                row.scope_department_id, frozenset({row.scope_department_id})
            )
        )
    return Scope(everywhere=True)


def holders(permission: Permission) -> list[tuple[User, list[Source]]]:
    """Every active person who holds `permission`, with the grants that give it."""
    base_roles = [
        role for role, urn in BASE_ROLES.items() if permission in SYSTEM_ROLE_PERMISSIONS[urn]
    ]
    role_ids = set(
        Role.objects.live()
        .filter(
            Q(
                is_system=True,
                urn__in=[
                    u.value for u, perms in SYSTEM_ROLE_PERMISSIONS.items() if permission in perms
                ],
            )
            | Q(is_system=False, permission_rows__permission_urn=permission.value)
        )
        .values_list("id", flat=True)
    )
    people = (
        User.objects.filter(is_active=True)
        .filter(
            Q(role__in=[r.value for r in base_roles])
            | Q(assignments__role_id__in=role_ids, assignments__ended_at__isnull=True)
        )
        .distinct()
        .order_by("username")
    )
    found = []
    for person in people:
        sources = Access.of(person).sources.get(permission)
        if sources:
            found.append((person, sources))
    return found


def role_permissions(role: Role) -> frozenset[Permission]:
    """The permissions `role` holds: from code for a system role, from its rows otherwise."""
    if role.is_system:
        return SYSTEM_ROLE_PERMISSIONS.get(SystemRole(role.urn), frozenset())
    return custom_permissions({role.id}).get(role.id, frozenset())


def role_scopes(permissions: frozenset[Permission]) -> list[ScopeKind]:
    """The scopes a role holding `permissions` may be granted at: those every one allows."""
    return [s for s in ScopeKind if all(s in PERMISSIONS[p].scopes for p in permissions)]


def scope_names(scope: Scope) -> dict[str, Any]:
    """A scope with team slugs and department codes in place of ids."""
    from apps.teams.models import Team

    return {
        "everywhere": scope.everywhere,
        "teams": sorted(Team.objects.filter(id__in=scope.team_ids).values_list("slug", flat=True)),
        "departments": sorted(
            Department.objects.filter(id__in=scope.department_ids).values_list("code", flat=True)
        ),
    }


def explained(user: User) -> list[dict[str, Any]]:
    """Every permission `user` holds, where it applies, and the grants behind it."""
    access = Access.of(user)
    return [
        {
            "urn": permission.value,
            "scope": scope_names(scope),
            "sources": [vars(s) for s in access.sources.get(permission, [])],
        }
        for permission, scope in sorted(access.scopes.items(), key=lambda item: item[0].value)
    ]
