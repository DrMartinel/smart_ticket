"""Support teams and who belongs to them (F2's tables; F13 fills memberships from Keycloak)."""

from __future__ import annotations

from enum import StrEnum

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class TeamStrategy(StrEnum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"


class MembershipRole(StrEnum):
    MEMBER = "member"
    LEAD = "lead"


class Team(BaseModel):
    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    strategy = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in TeamStrategy],
        default=TeamStrategy.LEAST_LOADED.value,
    )
    max_open_per_member = models.PositiveIntegerField(null=True, blank=True)
    keycloak_group = models.CharField(max_length=200, null=True, blank=True)
    is_fallback = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        db_table = "team_teams"
        constraints = [
            models.UniqueConstraint(
                fields=["is_fallback"],
                condition=models.Q(is_fallback=True),
                name="team_one_fallback",
            )
        ]

    def __str__(self) -> str:
        return self.slug


class TeamMembership(BaseModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    role = models.CharField(
        max_length=10,
        choices=[(r.value, r.value) for r in MembershipRole],
        default=MembershipRole.MEMBER.value,
    )
    is_available = models.BooleanField(default=True)
    last_assigned_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=[("keycloak", "keycloak"), ("local", "local")])

    class Meta(BaseModel.Meta):
        db_table = "team_memberships"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="uniq_team_membership")
        ]
