"""Support teams, the categories they own, who belongs to them and who is away (F2; F13 fills
memberships from Keycloak)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict, cast

from django.conf import settings
from django.db import models
from django.db.models import Count, Exists, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from apps.core.models import BaseModel
from infrastructure.dtos import TicketCategory

if TYPE_CHECKING:
    from django_stubs_ext import WithAnnotations


class TeamStrategy(StrEnum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"


class MembershipRole(StrEnum):
    MEMBER = "member"
    LEAD = "lead"


class TeamQuerySet(QuerySet["Team"]):
    def owning(self, category: str) -> Team | None:
        """The active team that owns `category`, if any."""
        return self.filter(is_active=True, categories__category=category).first()

    def fallback(self) -> Team | None:
        return self.filter(is_active=True, is_fallback=True).first()


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
    calendar = models.ForeignKey(
        "sla.Calendar", on_delete=models.PROTECT, null=True, blank=True, related_name="teams"
    )
    is_fallback = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = TeamQuerySet.as_manager()

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

    def membership_of(self, user: Any) -> TeamMembership | None:
        return self.memberships.filter(user=user).first()

    def is_lead(self, user: Any) -> bool:
        return self.memberships.filter(user=user, role=MembershipRole.LEAD.value).exists()


class TeamCategory(BaseModel):
    """A ticket category a team owns; each category has exactly one owner (BR-F2-01)."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="categories")
    category = models.CharField(
        max_length=20, unique=True, choices=[(c.value, c.value) for c in TicketCategory]
    )

    class Meta(BaseModel.Meta):
        db_table = "team_categories"


def open_tickets_of(user: Any) -> Subquery:
    """How many unfinished tickets the outer row's user holds, for annotations."""
    from apps.tickets.models import Ticket

    return Subquery(
        Ticket.objects.filter(assigned_to=OuterRef(user), resolved_at__isnull=True)
        .exclude(workflow_status__base__is_completed=True)
        .order_by()
        .values("assigned_to")
        .annotate(n=Count("id"))
        .values("n")
    )


class MembershipLoad(TypedDict):
    open_count: int
    on_leave: bool


class MembershipQuerySet(QuerySet["TeamMembership"]):
    def with_load(self, today: date) -> QuerySet[LoadedMembership]:
        """Memberships annotated with the member's open tickets and whether they're on leave."""
        loaded = self.select_related("user").annotate(
            open_count=Coalesce(open_tickets_of("user"), Value(0)),
            on_leave=Exists(
                Leave.objects.filter(
                    user=OuterRef("user"), starts_on__lte=today, ends_on__gte=today
                )
            ),
        )
        return cast("QuerySet[LoadedMembership]", loaded)

    def eligible(self, team: Team, today: date) -> QuerySet[LoadedMembership]:
        """Members who may get a new ticket now: active, available, not on leave, under the cap,
        ordered by the team's strategy (BR-F2-03)."""
        rows = self.filter(team=team, is_available=True, user__is_active=True).with_load(today)
        rows = rows.filter(Q(on_leave=False))
        if team.max_open_per_member is not None:
            rows = rows.filter(Q(open_count__lt=team.max_open_per_member))
        last = models.F("last_assigned_at").asc(nulls_first=True)
        if team.strategy == TeamStrategy.ROUND_ROBIN.value:
            return rows.order_by(last, "user__username")
        return rows.order_by("open_count", last, "user__username")


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

    objects = MembershipQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "team_memberships"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="uniq_team_membership")
        ]


if TYPE_CHECKING:
    LoadedMembership = WithAnnotations[TeamMembership, MembershipLoad]


class Leave(BaseModel):
    """Whole days a person is away; the strategy skips them (BR-F2-03)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leaves"
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    note = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "team_leaves"
        ordering = ["starts_on"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=models.F("starts_on")), name="team_leave_dates_ordered"
            )
        ]

    def covers(self, day: date) -> bool:
        return self.starts_on <= day <= self.ends_on


class Reassignment(BaseModel):
    """One manual reassignment, with its reason (BR-F2-05)."""

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="reassignments"
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    from_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, related_name="+")
    to_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, related_name="+")
    from_category = models.CharField(max_length=20, null=True)
    to_category = models.CharField(max_length=20, null=True)
    reason_code = models.CharField(max_length=30)
    note_masked = models.TextField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "team_reassignments"
        ordering = ["-created_at"]
