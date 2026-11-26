"""The permission catalogue and the system roles built from it (ADR-0045).

Permission and system-role URNs stay in code as enums so every `@require(...)` gate and
`Access.holds(...)` check is statically checked. Their metadata (labels, `staff_only`,
`locked`, `scopes`) and each system role's name and permission set live in `catalog.json`
beside this module and are validated 1:1 against the enums at import time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.accounts.models import Capability, UserRole

NID = "smart-ticket"
PERMISSION_PREFIX = f"urn:{NID}:perm:"
ROLE_PREFIX = f"urn:{NID}:role:"
PERMISSION_URN = re.compile(
    r"^urn:smart-ticket:perm:[a-z][a-z0-9-]{0,31}(:[a-z][a-z0-9-]{0,31}){1,2}$"
)
ROLE_URN = re.compile(r"^urn:smart-ticket:role:(system|custom):[a-z][a-z0-9-]{1,47}$")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,47}$")


class Permission(StrEnum):
    """Every action core-api gates, named by URN (BR-F14-20)."""

    ACCESS_GRANT = "urn:smart-ticket:perm:access:grant"
    ACCESS_GRANT_DELEGABLE = "urn:smart-ticket:perm:access:grant:delegable"
    ACCESS_PEOPLE_MANAGE = "urn:smart-ticket:perm:access:people:manage"
    ACCESS_PEOPLE_READ = "urn:smart-ticket:perm:access:people:read"
    ACCESS_READ = "urn:smart-ticket:perm:access:read"
    ACCESS_REVIEW_MANAGE = "urn:smart-ticket:perm:access:review:manage"
    ACCESS_REVIEW_RESPOND = "urn:smart-ticket:perm:access:review:respond"
    ACCESS_ROLES_MANAGE = "urn:smart-ticket:perm:access:roles:manage"
    AGENT_USE = "urn:smart-ticket:perm:agent:use"
    INCIDENTS_MANAGE = "urn:smart-ticket:perm:incidents:manage"
    INCIDENTS_READ = "urn:smart-ticket:perm:incidents:read"
    INCIDENTS_UNLINK = "urn:smart-ticket:perm:incidents:unlink"
    INFRA_OPERATE = "urn:smart-ticket:perm:infra:operate"
    INFRA_OPERATE_OWN = "urn:smart-ticket:perm:infra:operate:own"
    INFRA_READ = "urn:smart-ticket:perm:infra:read"
    INFRA_READ_OWN = "urn:smart-ticket:perm:infra:read:own"
    KB_AUTHORITY_LOG_READ = "urn:smart-ticket:perm:kb:authority-log:read"
    KB_AUTHORITY_GRANT = "urn:smart-ticket:perm:kb:authority:grant"
    KB_AUTHORITY_QUEUE = "urn:smart-ticket:perm:kb:authority:queue"
    KB_AUTHORITY_RISK_TIER = "urn:smart-ticket:perm:kb:authority:risk-tier"
    KB_DRAFTS_MANAGE = "urn:smart-ticket:perm:kb:drafts:manage"
    KB_DRAFTS_WITHDRAW_ANY = "urn:smart-ticket:perm:kb:drafts:withdraw-any"
    KB_GAPS_MANAGE = "urn:smart-ticket:perm:kb:gaps:manage"
    KB_GRAPH_EDIT = "urn:smart-ticket:perm:kb:graph:edit"
    KB_GRAPH_READ = "urn:smart-ticket:perm:kb:graph:read"
    KB_GRAPH_REBUILD = "urn:smart-ticket:perm:kb:graph:rebuild"
    KB_PAGES_CREATE = "urn:smart-ticket:perm:kb:pages:create"
    KB_PAGES_READ = "urn:smart-ticket:perm:kb:pages:read"
    KB_PAGES_REINGEST = "urn:smart-ticket:perm:kb:pages:reingest"
    NOTIFICATIONS_DELIVERIES_MANAGE = "urn:smart-ticket:perm:notifications:deliveries:manage"
    NOTIFICATIONS_MATRIX_MANAGE = "urn:smart-ticket:perm:notifications:matrix:manage"
    NOTIFICATIONS_MATRIX_READ = "urn:smart-ticket:perm:notifications:matrix:read"
    NOTIFICATIONS_TEMPLATES_MANAGE = "urn:smart-ticket:perm:notifications:templates:manage"
    NOTIFICATIONS_WEBHOOKS_MANAGE = "urn:smart-ticket:perm:notifications:webhooks:manage"
    ORG_DEPARTMENTS_MANAGE = "urn:smart-ticket:perm:org:departments:manage"
    ORG_DEPARTMENTS_READ = "urn:smart-ticket:perm:org:departments:read"
    ORG_IMPORT = "urn:smart-ticket:perm:org:import"
    PII_ACCESS_LOG_READ = "urn:smart-ticket:perm:pii:access-log:read"
    PII_REVEAL = "urn:smart-ticket:perm:pii:reveal"
    PII_REVEAL_ANY = "urn:smart-ticket:perm:pii:reveal:any"
    REPORTS_DASHBOARD_READ = "urn:smart-ticket:perm:reports:dashboard:read"
    REPORTS_INCIDENTS_READ = "urn:smart-ticket:perm:reports:incidents:read"
    REPORTS_KB_READ = "urn:smart-ticket:perm:reports:kb:read"
    REPORTS_NOTIFICATIONS_READ = "urn:smart-ticket:perm:reports:notifications:read"
    REPORTS_OPERATIONS_READ = "urn:smart-ticket:perm:reports:operations:read"
    REPORTS_REVIEWERS_ALL = "urn:smart-ticket:perm:reports:reviewers:all"
    REPORTS_ROLLOUT_READ = "urn:smart-ticket:perm:reports:rollout:read"
    REPORTS_SECURITY_READ = "urn:smart-ticket:perm:reports:security:read"
    REPORTS_SECURITY_DETAIL = "urn:smart-ticket:perm:reports:security:detail"
    REPORTS_TEAMS_READ = "urn:smart-ticket:perm:reports:teams:read"
    REQUESTER_CHAT = "urn:smart-ticket:perm:requester:chat"
    REQUESTER_DEPARTMENT_READ = "urn:smart-ticket:perm:requester:department:read"
    REQUESTER_SUBMIT = "urn:smart-ticket:perm:requester:submit"
    REQUESTER_TICKET_STATUS = "urn:smart-ticket:perm:requester:ticket-status"
    REQUESTER_TICKETS = "urn:smart-ticket:perm:requester:tickets"
    REVIEW_FEWSHOT_READ = "urn:smart-ticket:perm:review:fewshot:read"
    REVIEW_QUEUE_WORK = "urn:smart-ticket:perm:review:queue:work"
    ROLLOUT_FLAG_OFF = "urn:smart-ticket:perm:rollout:flag:off"
    ROLLOUT_FLAG_ON = "urn:smart-ticket:perm:rollout:flag:on"
    ROLLOUT_GATES_MANAGE = "urn:smart-ticket:perm:rollout:gates:manage"
    ROLLOUT_READ = "urn:smart-ticket:perm:rollout:read"
    ROLLOUT_THRESHOLDS_READ = "urn:smart-ticket:perm:rollout:thresholds:read"
    RUNBOOKS_CATALOG_ACTIVATE = "urn:smart-ticket:perm:runbooks:catalog:activate"
    RUNBOOKS_CATALOG_MANAGE = "urn:smart-ticket:perm:runbooks:catalog:manage"
    RUNBOOKS_CATALOG_READ = "urn:smart-ticket:perm:runbooks:catalog:read"
    RUNBOOKS_EXECUTE = "urn:smart-ticket:perm:runbooks:execute"
    SECURITY_QUEUE_WORK = "urn:smart-ticket:perm:security:queue:work"
    SECURITY_SUMMARY_READ = "urn:smart-ticket:perm:security:summary:read"
    SELF_NOTIFICATIONS = "urn:smart-ticket:perm:self:notifications"
    SELF_PROFILE = "urn:smart-ticket:perm:self:profile"
    SELF_SESSIONS = "urn:smart-ticket:perm:self:sessions"
    SLA_MANAGE = "urn:smart-ticket:perm:sla:manage"
    SLA_POLICIES_ACTIVATE = "urn:smart-ticket:perm:sla:policies:activate"
    SLA_READ = "urn:smart-ticket:perm:sla:read"
    TEAMS_AVAILABILITY_MANAGE = "urn:smart-ticket:perm:teams:availability:manage"
    TEAMS_AVAILABILITY_OWN = "urn:smart-ticket:perm:teams:availability:own"
    TEAMS_LEAD = "urn:smart-ticket:perm:teams:lead"
    TEAMS_MANAGE = "urn:smart-ticket:perm:teams:manage"
    TEAMS_READ = "urn:smart-ticket:perm:teams:read"
    TEAMS_SUPERVISE = "urn:smart-ticket:perm:teams:supervise"
    TICKETS_ALL_CATEGORIES = "urn:smart-ticket:perm:tickets:all-categories"
    TICKETS_COMMENT = "urn:smart-ticket:perm:tickets:comment"
    TICKETS_FIELDS_WRITE = "urn:smart-ticket:perm:tickets:fields:write"
    TICKETS_LIFECYCLE_READ = "urn:smart-ticket:perm:tickets:lifecycle:read"
    TICKETS_MOVE = "urn:smart-ticket:perm:tickets:move"
    TICKETS_MOVE_FORCE = "urn:smart-ticket:perm:tickets:move:force"
    TICKETS_PRIORITY = "urn:smart-ticket:perm:tickets:priority"
    TICKETS_READ = "urn:smart-ticket:perm:tickets:read"
    TICKETS_REASSIGN = "urn:smart-ticket:perm:tickets:reassign"
    TICKETS_SLA_REBUILD = "urn:smart-ticket:perm:tickets:sla:rebuild"
    TICKETS_TAKE = "urn:smart-ticket:perm:tickets:take"
    TICKETS_TRANSFERS_RETRY = "urn:smart-ticket:perm:tickets:transfers:retry"
    TICKETS_WORKFLOW_CHANGE = "urn:smart-ticket:perm:tickets:workflow:change"
    WORKFLOWS_MANAGE = "urn:smart-ticket:perm:workflows:manage"
    WORKFLOWS_READ = "urn:smart-ticket:perm:workflows:read"


class ScopeKind(StrEnum):
    GLOBAL = "global"
    TEAM = "team"
    DEPARTMENT = "department"


@dataclass(frozen=True)
class PermissionSpec:
    """What a permission is, for the console's catalogue and the grant rules."""

    label: str
    staff_only: bool
    locked: bool
    scopes: tuple[ScopeKind, ...]


def area_of(permission: Permission) -> str:
    """The permission's area, its first segment after `perm`."""
    return permission.value.removeprefix(PERMISSION_PREFIX).split(":")[0]


class SystemRole(StrEnum):
    """The roles defined in code (BR-F14-09); copied but never edited or retired."""

    EMPLOYEE = "urn:smart-ticket:role:system:employee"
    TECHNICIAN = "urn:smart-ticket:role:system:technician"
    MANAGER = "urn:smart-ticket:role:system:manager"
    SECURITY = "urn:smart-ticket:role:system:security"
    WORKFLOW_ADMIN = "urn:smart-ticket:role:system:workflow-admin"
    KB_EDITOR = "urn:smart-ticket:role:system:kb-editor"
    INCIDENT_MANAGER = "urn:smart-ticket:role:system:incident-manager"
    TEAM_LEAD = "urn:smart-ticket:role:system:team-lead"
    DEPARTMENT_HEAD = "urn:smart-ticket:role:system:department-head"


BASE_ROLES: dict[UserRole, SystemRole] = {
    UserRole.EMPLOYEE: SystemRole.EMPLOYEE,
    UserRole.TECHNICIAN: SystemRole.TECHNICIAN,
    UserRole.MANAGER: SystemRole.MANAGER,
    UserRole.SECURITY: SystemRole.SECURITY,
}
ADD_ON_ROLES: dict[Capability, SystemRole] = {
    Capability.WORKFLOW_ADMIN: SystemRole.WORKFLOW_ADMIN,
    Capability.KB_EDITOR: SystemRole.KB_EDITOR,
    Capability.INCIDENT_MANAGER: SystemRole.INCIDENT_MANAGER,
}
STRUCTURAL_ROLES = frozenset({SystemRole.TEAM_LEAD, SystemRole.DEPARTMENT_HEAD})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PermissionEntry(_Strict):
    label: str = Field(min_length=1)
    staff_only: bool = True
    locked: bool = False
    scopes: tuple[ScopeKind, ...] = (ScopeKind.GLOBAL,)

    @field_validator("label")
    @classmethod
    def non_blank_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value

    @field_validator("scopes")
    @classmethod
    def valid_scopes(cls, value: tuple[ScopeKind, ...]) -> tuple[ScopeKind, ...]:
        if ScopeKind.GLOBAL not in value:
            raise ValueError("scopes must include 'global'")
        if len(value) != len(set(value)):
            raise ValueError("scopes must not contain duplicates")
        return value


class _SystemRoleEntry(_Strict):
    name: str = Field(min_length=1)
    permissions: tuple[Permission, ...]

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: tuple[Permission, ...]) -> tuple[Permission, ...]:
        if len(value) != len(set(value)):
            raise ValueError("system role permissions must not contain duplicates")
        return value


class _CatalogData(_Strict):
    permissions: dict[Permission, _PermissionEntry]
    system_roles: dict[SystemRole, _SystemRoleEntry]

    @model_validator(mode="after")
    def matches_enums(self) -> _CatalogData:
        missing_perms = set(Permission) - set(self.permissions)
        if missing_perms:
            names = ", ".join(sorted(p.value for p in missing_perms))
            raise ValueError(f"catalog is missing permissions: {names}")
        missing_roles = set(SystemRole) - set(self.system_roles)
        if missing_roles:
            names = ", ".join(sorted(r.value for r in missing_roles))
            raise ValueError(f"catalog is missing system roles: {names}")
        employee_staff_only = sorted(
            p.value
            for p in self.system_roles[SystemRole.EMPLOYEE].permissions
            if self.permissions[p].staff_only
        )
        if employee_staff_only:
            raise ValueError(
                f"employee system role holds staff-only permissions: {', '.join(employee_staff_only)}"
            )
        return self


@dataclass(frozen=True)
class Catalog:
    """Loaded and validated permission metadata and system role matrix."""

    permissions: dict[Permission, PermissionSpec]
    system_role_permissions: dict[SystemRole, frozenset[Permission]]
    system_role_names: dict[SystemRole, str]


CATALOG_PATH = Path(__file__).with_name("catalog.json")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate key in catalog JSON: {key!r}")
        obj[key] = value
    return obj


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    """Loads `path` and validates it 1:1 against `Permission` and `SystemRole`."""
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    data = _CatalogData.model_validate(raw)
    return Catalog(
        permissions={
            permission: PermissionSpec(
                label=entry.label,
                staff_only=entry.staff_only,
                locked=entry.locked,
                scopes=entry.scopes,
            )
            for permission, entry in data.permissions.items()
        },
        system_role_permissions={
            role: frozenset(entry.permissions) for role, entry in data.system_roles.items()
        },
        system_role_names={role: entry.name for role, entry in data.system_roles.items()},
    )


_CATALOG = load_catalog()
PERMISSIONS: dict[Permission, PermissionSpec] = _CATALOG.permissions
SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[Permission]] = _CATALOG.system_role_permissions
SYSTEM_ROLE_NAMES: dict[SystemRole, str] = _CATALOG.system_role_names


def custom_role_urn(name: str) -> str:
    """The URN of a custom role called `name`, e.g. "Read-only auditor" → `…:custom:read-only-auditor`."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return f"{ROLE_PREFIX}custom:{slug}"


def is_role_urn(value: str) -> bool:
    return bool(ROLE_URN.match(value))


def is_permission_urn(value: str) -> bool:
    return bool(PERMISSION_URN.match(value))


def permissions_scopable_at(permissions: frozenset[Permission], scope: ScopeKind) -> bool:
    """Whether every one of `permissions` may be granted at `scope`."""
    return all(scope in PERMISSIONS[p].scopes for p in permissions)
