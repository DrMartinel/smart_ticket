"""Teams and their categories, members and fallback, each change audited with a reason (UC-F2-06)."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.accounts.models import AuthSource, User
from apps.audit.models import AuditLog
from apps.teams.models import MembershipRole, Team, TeamCategory, TeamMembership
from apps.teams.utils.assignment import TeamError
from apps.teams.utils.vocabulary import TeamRefusal
from infrastructure.dtos import TicketCategory

_FIELDS = ("name", "strategy", "max_open_per_member", "keycloak_group", "is_active", "is_fallback")


class TeamConfig:
    """Creates and edits teams so every category keeps exactly one owner (BR-F2-01)."""

    def save(self, actor: User, slug: str, data: dict[str, Any], *, create: bool) -> Team:
        """Creates or updates a team; `categories`, when given, is the full set it owns."""
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise TeamError(422, TeamRefusal.REASON_REQUIRED, "say why the team changes")
        with transaction.atomic():
            team = Team(slug=slug) if create else self.locked(slug)
            before = self.snapshot(team) if not create else None
            for name in _FIELDS:
                if data.get(name) is not None:
                    setattr(team, name, data[name])
            if data.get("is_fallback"):
                Team.objects.exclude(pk=team.pk).filter(is_fallback=True).update(is_fallback=False)
            team.save()
            if data.get("categories") is not None:
                self.set_categories(
                    team, data["categories"], move=bool(data.get("move_categories"))
                )
            self.check_whole(team)
            AuditLog.objects.record(
                "team_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "team": team.slug,
                    "reason": reason,
                    "before": before,
                    "after": self.snapshot(team),
                },
            )
        return team

    def set_categories(self, team: Team, categories: list[str], *, move: bool) -> None:
        """Makes `categories` the team's; refuses one another team owns unless asked to move it."""
        wanted = set(categories)
        owned_elsewhere = TeamCategory.objects.filter(category__in=wanted).exclude(team=team)
        taken = list(owned_elsewhere.select_related("team"))
        if taken and not move:
            first = taken[0]
            raise TeamError(
                409,
                TeamRefusal.CATEGORY_TAKEN,
                f"{first.category} belongs to team {first.team.slug}",
                {"category": first.category, "team": first.team.slug},
            )
        owned_elsewhere.delete()
        team.categories.exclude(category__in=wanted).delete()
        for category in wanted - set(team.categories.values_list("category", flat=True)):
            TeamCategory.objects.create(team=team, category=category)

    def check_whole(self, team: Team) -> None:
        """Every category owned by an active team, and one active fallback team."""
        owned = set(
            TeamCategory.objects.filter(team__is_active=True).values_list("category", flat=True)
        )
        missing = sorted(c.value for c in TicketCategory if c.value not in owned)
        if missing:
            raise TeamError(
                422,
                TeamRefusal.CATEGORY_UNOWNED,
                f"no active team would own {', '.join(missing)}",
                {"categories": missing},
            )
        if not Team.objects.filter(is_active=True, is_fallback=True).exists():
            raise TeamError(
                422, TeamRefusal.FALLBACK_REQUIRED, "one active team must be the fallback"
            )

    def locked(self, slug: str) -> Team:
        team = Team.objects.select_for_update().filter(slug=slug).first()
        if team is None:
            raise TeamError(404, TeamRefusal.TEAM_NOT_FOUND, f"no team {slug!r}")
        return team

    def snapshot(self, team: Team) -> dict[str, Any]:
        return {
            **{name: getattr(team, name) for name in _FIELDS},
            "categories": sorted(team.categories.values_list("category", flat=True)),
        }

    # ── members (local users; Keycloak users' teams come from their groups, FR-F2-015) ──

    def add_member(
        self, actor: User, team: Team, user: User, role: MembershipRole
    ) -> TeamMembership:
        if user.auth_source == AuthSource.OIDC.value:
            raise TeamError(
                409,
                TeamRefusal.MANAGED_BY_KEYCLOAK,
                f"{user.username}'s teams come from Keycloak groups",
            )
        with transaction.atomic():
            member, _ = TeamMembership.objects.update_or_create(
                team=team, user=user, defaults={"role": role.value, "source": "local"}
            )
            self.audit_member("added", actor, team, user, role.value)
        return member

    def remove_member(self, actor: User, team: Team, user: User) -> None:
        member = TeamMembership.objects.filter(team=team, user=user).first()
        if member is None:
            return
        if member.source == "keycloak":
            raise TeamError(
                409,
                TeamRefusal.MANAGED_BY_KEYCLOAK,
                f"{user.username}'s teams come from Keycloak groups",
            )
        with transaction.atomic():
            self.audit_member("removed", actor, team, user, member.role)
            member.delete()

    def audit_member(self, change: str, actor: User, team: Team, user: User, role: str) -> None:
        AuditLog.objects.record(
            "membership_changed",
            actor_type="human",
            actor_id=actor.id,
            payload={"change": change, "team": team.slug, "user": user.username, "role": role},
        )


# --- the team configuration service ---

team_config = TeamConfig()
