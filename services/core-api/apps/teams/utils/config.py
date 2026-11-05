"""Teams and their categories, members and fallback, each change audited with a reason (UC-F2-06)."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.accounts.models import User
from apps.accounts.utils.grants import grants
from apps.audit.models import AuditLog
from apps.teams.models import MembershipRole, Team, TeamCategory, TeamMembership
from apps.teams.utils.assignment import TeamError
from apps.teams.utils.vocabulary import TeamRefusal
from infrastructure.dtos import TicketCategory

_FIELDS = ("name", "strategy", "max_open_per_member", "is_active", "is_fallback")


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

    # ── members ──

    def add_member(
        self, actor: User, team: Team, user: User, role: MembershipRole
    ) -> TeamMembership:
        if not (user.is_active and user.is_support_staff):
            raise TeamError(
                422, TeamRefusal.NOT_SUPPORT_STAFF, f"{user.username} isn't active support staff"
            )
        with transaction.atomic():
            member, _ = TeamMembership.objects.update_or_create(
                team=team, user=user, defaults={"role": role.value}
            )
            grants.set_team_lead(actor, team, user, lead=role is MembershipRole.LEAD)
            self.audit_member("added", actor, team, user, role.value)
        return member

    def remove_member(self, actor: User, team: Team, user: User) -> None:
        member = TeamMembership.objects.filter(team=team, user=user).first()
        if member is None:
            return
        with transaction.atomic():
            self.leave(actor, member, "removed")

    def leave(self, actor: User | None, member: TeamMembership, reason: str) -> None:
        """Removes a membership and the team-lead grant that came with it."""
        self.audit_member("removed", actor, member.team, member.user, member.role, reason)
        grants.set_team_lead(actor, member.team, member.user, lead=False)
        member.delete()

    def audit_member(
        self,
        change: str,
        actor: User | None,
        team: Team,
        user: User,
        role: str,
        reason: str = "",
    ) -> None:
        AuditLog.objects.record(
            "membership_changed",
            actor_type="human" if actor else "system",
            actor_id=actor.id if actor else None,
            payload={
                "change": change,
                "team": team.slug,
                "user": user.username,
                "role": role,
                **({"reason": reason} if reason else {}),
            },
        )


# --- the team configuration service ---

team_config = TeamConfig()
