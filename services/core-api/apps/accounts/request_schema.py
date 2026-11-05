"""Request shapes for the account endpoints."""

from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema

from apps.accounts.models import NoAnswer, ReviewDecisionKind, UserRole
from apps.accounts.utils.catalog import ScopeKind


class OidcExchangeIn(Schema):
    """What the callback page sends after Keycloak redirects back (F13)."""

    code: str = Field(min_length=1, max_length=4096)
    code_verifier: str = Field(min_length=43, max_length=128)
    nonce: str = Field(min_length=1, max_length=256)
    redirect_uri: str = Field(min_length=1, max_length=500)


class LoginIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=4096)


class BaseRoleIn(Schema):
    role: UserRole
    reason: str = Field("", max_length=500)


class ReasonIn(Schema):
    reason: str = Field(min_length=1, max_length=500)


class RoleIn(Schema):
    """A new custom role; its URN is made from `name` (BR-F14-19)."""

    name: str = Field(min_length=2, max_length=120)
    description: str = Field("", max_length=500)
    permissions: list[str] = Field(min_length=1, max_length=200)
    delegable: bool = False
    reason: str = Field(min_length=1, max_length=500)


class RolePatchIn(Schema):
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=500)
    permissions: list[str] | None = Field(None, max_length=200)
    delegable: bool | None = None
    reason: str = Field(min_length=1, max_length=500)


class DelegatedGrantIn(Schema):
    """A delegable role for someone in the department, at that department."""

    username: str = Field(min_length=1, max_length=150)
    role: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    ends_at: datetime | None = None


class GrantIn(Schema):
    """A role at a scope: `scope` is a team slug or department code, none for global."""

    role: str = Field(min_length=1, max_length=120)
    scope_kind: ScopeKind = ScopeKind.GLOBAL
    scope: str | None = Field(None, max_length=60)
    reason: str = Field(min_length=1, max_length=500)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class ExtendIn(Schema):
    ends_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)


class DepartmentIn(Schema):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    parent: str | None = Field(None, max_length=30)
    head: str | None = Field(None, max_length=150)
    cost_centre: str = Field("", max_length=40)
    reason: str = Field(min_length=1, max_length=500)


class DepartmentPatchIn(Schema):
    """None leaves a field; `head` "" removes the head."""

    name: str | None = Field(None, min_length=1, max_length=120)
    head: str | None = Field(None, max_length=150)
    cost_centre: str | None = Field(None, max_length=40)
    reason: str = Field(min_length=1, max_length=500)


class PlaceIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    reason: str = Field(min_length=1, max_length=500)


class DepartmentMoveIn(Schema):
    parent: str | None = Field(None, max_length=30)
    reason: str = Field(min_length=1, max_length=500)


class ImportIn(Schema):
    csv: str = Field(min_length=1, max_length=2_000_000)
    reason: str = Field(min_length=1, max_length=500)


class ProfileIn(Schema):
    """None leaves a field; `line_manager` "" removes the line manager."""

    first_name: str | None = Field(None, max_length=150)
    last_name: str | None = Field(None, max_length=150)
    job_title: str | None = Field(None, max_length=120)
    location: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)
    employee_id: str | None = Field(None, max_length=40)
    department: str | None = Field(None, max_length=30)
    line_manager: str | None = Field(None, max_length=150)
    reason: str = Field(min_length=1, max_length=500)


class ProvisionIn(ProfileIn):
    username: str = Field(min_length=2, max_length=150, pattern=r"^[A-Za-z0-9._@+-]+$")
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CampaignIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    fallback_reviewer: str = Field(min_length=1, max_length=150)
    on_no_answer: NoAnswer = NoAnswer.FLAG
    role: str | None = Field(None, max_length=120)
    department: str | None = Field(None, max_length=30)
    closes_at: datetime | None = None


class DecideIn(Schema):
    decision: ReviewDecisionKind
    note: str = Field("", max_length=500)
