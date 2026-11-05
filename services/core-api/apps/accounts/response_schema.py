"""
Response shapes for the account endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema

from apps.accounts.models import (
    AccessReviewCampaign,
    AccessReviewItem,
    Assignment,
    Department,
    Role,
    User,
)
from apps.accounts.utils.access import Access, Source, role_permissions, role_scopes
from apps.accounts.utils.catalog import PERMISSIONS, Permission, area_of


class UserTeamOut(Schema):
    team: str
    role: str


class StaffOut(Schema):
    username: str
    role: str


class DepartmentRefOut(Schema):
    code: str
    name: str


class AccountOut(Schema):
    username: str
    name: str
    email: str
    role: str
    capabilities: list[str]
    teams: list[UserTeamOut]
    auth_source: str
    is_active: bool
    is_break_glass: bool
    last_login: datetime | None
    status: str = "active"
    department: DepartmentRefOut | None = None
    line_manager: str | None = None
    job_title: str = ""

    @staticmethod
    def resolve_department(user: User) -> DepartmentRefOut | None:
        department = user.department
        return DepartmentRefOut(code=department.code, name=department.name) if department else None

    @staticmethod
    def resolve_line_manager(user: User) -> str | None:
        return user.line_manager.username if user.line_manager else None

    @staticmethod
    def resolve_name(user: User) -> str:
        return user.get_full_name()

    @staticmethod
    def resolve_capabilities(user: User) -> list[str]:
        return sorted(user.capability_set())

    @staticmethod
    def resolve_teams(user: User) -> list[UserTeamOut]:
        return sorted(
            (UserTeamOut(team=m.team.slug, role=m.role) for m in user.team_memberships.all()),
            key=lambda t: t.team,
        )


class UserOut(Schema):
    id: uuid.UUID
    username: str
    email: str
    role: str
    auth_source: str = "local"
    language: str = "vi"
    capabilities: list[str] = []
    teams: list[UserTeamOut] = []
    # Every permission the person holds somewhere; navigation reads this (FR-F14-013).
    permissions: list[str] = []
    permissions_everywhere: list[str] = []
    status: str = "active"
    name: str = ""
    department: DepartmentRefOut | None = None
    line_manager: str | None = None
    job_title: str = ""
    location: str = ""

    @staticmethod
    def resolve_permissions(user: User) -> list[str]:
        return Access.of(user).permissions()

    @staticmethod
    def resolve_permissions_everywhere(user: User) -> list[str]:
        access = Access.of(user)
        return [p for p in access.permissions() if access.holds_everywhere(Permission(p))]

    @staticmethod
    def resolve_name(user: User) -> str:
        return user.get_full_name()

    @staticmethod
    def resolve_department(user: User) -> DepartmentRefOut | None:
        department = user.department
        return DepartmentRefOut(code=department.code, name=department.name) if department else None

    @staticmethod
    def resolve_line_manager(user: User) -> str | None:
        return user.line_manager.username if user.line_manager else None

    @staticmethod
    def resolve_capabilities(user: User) -> list[str]:
        return sorted(user.capability_set())

    @staticmethod
    def resolve_teams(user: User) -> list[UserTeamOut]:
        return [
            UserTeamOut(team=m.team.slug, role=m.role)
            for m in user.team_memberships.select_related("team").order_by("team__slug")
        ]


class OidcConfigOut(Schema):
    issuer: str
    client_id: str
    authorize_url: str
    scopes: str


class SessionOut(Schema):
    access: str
    access_expires_at: datetime
    user: UserOut


class SignInOut(Schema):
    id: uuid.UUID
    family: uuid.UUID
    client: str
    user_agent: str
    ip_address: str | None
    created_at: datetime
    expires_at: datetime
    family_expires_at: datetime


class RefusedOut(Schema):
    detail: str


# ── F14: permissions, roles, grants, departments, reviews ──


class PermissionOut(Schema):
    urn: str
    area: str
    label: str
    staff_only: bool
    locked: bool
    scopes: list[str]

    @classmethod
    def of(cls, permission: Permission) -> PermissionOut:
        spec = PERMISSIONS[permission]
        return cls(
            urn=permission.value,
            area=area_of(permission),
            label=spec.label,
            staff_only=spec.staff_only,
            locked=spec.locked,
            scopes=[s.value for s in spec.scopes],
        )


class RoleOut(Schema):
    urn: str
    name: str
    description: str
    is_system: bool
    delegable: bool = False
    created_at: datetime
    retired_at: datetime | None
    permissions: list[str]
    scopes: list[str]
    holders: int

    @classmethod
    def of(cls, role: Role, holders: int = 0) -> RoleOut:
        permissions = role_permissions(role)
        return cls(
            urn=role.urn,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            delegable=role.delegable,
            created_at=role.created_at,
            retired_at=role.retired_at,
            permissions=sorted(p.value for p in permissions),
            scopes=[s.value for s in role_scopes(permissions)],
            holders=holders,
        )


class AssignmentOut(Schema):
    id: uuid.UUID
    user: str
    role: str
    role_name: str
    scope_kind: str
    scope: str
    source: str
    granted_by: str | None
    reason: str
    starts_at: datetime
    ends_at: datetime | None
    ended_at: datetime | None
    ended_reason: str
    needs_review: bool
    review_due_at: datetime | None
    reviewed_at: datetime | None
    active: bool

    @classmethod
    def of(cls, row: Assignment, now: datetime) -> AssignmentOut:
        return cls(
            id=row.id,
            user=row.user.username,
            role=row.role.urn,
            role_name=row.role.name,
            scope_kind=row.scope_kind,
            scope=row.scope_label(),
            source=row.source,
            granted_by=row.granted_by.username if row.granted_by else None,
            reason=row.reason,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            ended_at=row.ended_at,
            ended_reason=row.ended_reason,
            needs_review=row.needs_review,
            review_due_at=row.review_due_at,
            reviewed_at=row.reviewed_at,
            active=row.is_active_at(now) and row.role.retired_at is None,
        )


class SourceOut(Schema):
    role_urn: str
    role_name: str
    scope: str
    assignment_id: uuid.UUID | None
    granted_by: str | None
    granted_at: str | None
    ends_at: str | None

    @classmethod
    def of(cls, source: Source) -> SourceOut:
        return cls(**vars(source))


class ScopeOut(Schema):
    everywhere: bool
    teams: list[str]
    departments: list[str]


class EffectivePermissionOut(Schema):
    urn: str
    scope: ScopeOut
    sources: list[SourceOut]


class PersonAccessOut(Schema):
    """A person's effective access and where each permission comes from (FR-F14-011)."""

    username: str
    role: str
    permissions: list[EffectivePermissionOut]


class ExplainOut(Schema):
    username: str
    permission: str
    holds: bool
    scope: ScopeOut | None
    sources: list[SourceOut]


class HolderOut(Schema):
    username: str
    name: str
    role: str
    sources: list[SourceOut]


class DepartmentOut(Schema):
    code: str
    name: str
    parent: str | None
    head: str | None
    cost_centre: str
    is_default: bool
    archived_at: datetime | None
    people: int

    @classmethod
    def of(cls, department: Department, people: int = 0) -> DepartmentOut:
        return cls(
            code=department.code,
            name=department.name,
            parent=department.parent.code if department.parent else None,
            head=department.head.username if department.head else None,
            cost_centre=department.cost_centre,
            is_default=department.is_default,
            archived_at=department.archived_at,
            people=people,
        )


class ImportRowOut(Schema):
    line: int
    key: str
    action: str
    errors: list[str]


class ImportOut(Schema):
    applied: bool
    dry_run: bool
    rows: list[ImportRowOut]


class PersonRecordOut(AccountOut):
    """One person's record for the console's person page."""

    first_name: str
    last_name: str
    location: str
    phone: str
    employee_id: str
    date_joined: datetime


class ReviewItemOut(Schema):
    id: uuid.UUID
    campaign: uuid.UUID
    campaign_name: str
    closes_at: datetime
    user: str
    user_name: str
    role: str
    role_name: str
    scope: str
    granted_by: str | None
    granted_at: datetime
    reviewer: str
    decision: str
    note: str
    decided_at: datetime | None

    @classmethod
    def of(cls, item: AccessReviewItem) -> ReviewItemOut:
        row = item.assignment
        return cls(
            id=item.id,
            campaign=item.campaign_id,
            campaign_name=item.campaign.name,
            closes_at=item.campaign.closes_at,
            user=row.user.username,
            user_name=row.user.get_full_name(),
            role=row.role.urn,
            role_name=row.role.name,
            scope=row.scope_label(),
            granted_by=row.granted_by.username if row.granted_by else None,
            granted_at=row.starts_at,
            reviewer=item.reviewer.username,
            decision=item.decision,
            note=item.note,
            decided_at=item.decided_at,
        )


class CampaignOut(Schema):
    id: uuid.UUID
    name: str
    role: str | None
    department: str | None
    on_no_answer: str
    fallback_reviewer: str
    state: str
    created_by: str
    opened_at: datetime
    closes_at: datetime
    closed_at: datetime | None
    total: int
    kept: int
    revoked: int
    pending: int

    @classmethod
    def of(cls, campaign: AccessReviewCampaign, counts: dict[str, int]) -> CampaignOut:
        return cls(
            id=campaign.id,
            name=campaign.name,
            role=campaign.role.urn if campaign.role else None,
            department=campaign.department.code if campaign.department else None,
            on_no_answer=campaign.on_no_answer,
            fallback_reviewer=campaign.fallback_reviewer.username,
            state=campaign.state,
            created_by=campaign.created_by.username,
            opened_at=campaign.opened_at,
            closes_at=campaign.closes_at,
            closed_at=campaign.closed_at,
            total=counts.get("total", 0),
            kept=counts.get("kept", 0),
            revoked=counts.get("revoked", 0),
            pending=counts.get("pending", 0),
        )


class CampaignDetailOut(CampaignOut):
    items: list[ReviewItemOut] = []


class DepartmentTicketOut(Schema):
    """A ticket raised in a department its head may read, masked (BR-F14-11)."""

    public_id: str
    subject_masked: str
    requester: str
    requester_name: str
    department: str | None
    status_label: str
    team: str | None
    created_at: datetime
    resolved_at: datetime | None
