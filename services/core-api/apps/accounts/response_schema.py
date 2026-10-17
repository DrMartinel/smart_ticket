"""
Response shapes for the account endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema

from apps.accounts.models import User


class TeamOut(Schema):
    team: str
    role: str


class UserOut(Schema):
    id: uuid.UUID
    username: str
    email: str
    role: str
    auth_source: str = "local"
    language: str = "vi"
    capabilities: list[str] = []
    teams: list[TeamOut] = []

    @staticmethod
    def resolve_capabilities(user: User) -> list[str]:
        return sorted(user.capability_set())

    @staticmethod
    def resolve_teams(user: User) -> list[TeamOut]:
        return [
            TeamOut(team=m.team.slug, role=m.role)
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
