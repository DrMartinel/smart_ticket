"""Request bodies of the team, assignment and availability endpoints (F2)."""

from __future__ import annotations

import datetime
from typing import Literal

from ninja import Schema
from pydantic import Field

from apps.teams.models import TeamStrategy
from apps.teams.utils.vocabulary import ReassignReason
from infrastructure.dtos import TicketCategory


class TeamIn(Schema):
    slug: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=100)
    categories: list[TicketCategory] = Field(default_factory=list)
    strategy: TeamStrategy = TeamStrategy.LEAST_LOADED
    max_open_per_member: int | None = Field(None, ge=1)
    keycloak_group: str | None = Field(None, max_length=200)
    is_fallback: bool = False
    move_categories: bool = False
    reason: str = Field("", max_length=500)


class TeamPatch(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    categories: list[TicketCategory] | None = None
    strategy: TeamStrategy | None = None
    max_open_per_member: int | None = Field(None, ge=1)
    keycloak_group: str | None = Field(None, max_length=200)
    is_fallback: bool | None = None
    is_active: bool | None = None
    move_categories: bool = False
    reason: str = Field("", max_length=500)


class MemberIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    role: Literal["member", "lead"] = "member"


class TakeIn(Schema):
    expected_version: int


class ReassignIn(Schema):
    to_user: str | None = Field(None, max_length=150)
    to_team: str | None = Field(None, max_length=50)
    to_category: TicketCategory | None = None
    reason_code: ReassignReason
    note: str = Field("", max_length=1000)
    expected_version: int


class AvailabilityIn(Schema):
    is_available: bool


class LeaveIn(Schema):
    starts_on: datetime.date
    ends_on: datetime.date
    note: str = Field("", max_length=500)
    user: str | None = Field(None, max_length=150)
