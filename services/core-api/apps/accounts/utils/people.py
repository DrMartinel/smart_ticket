"""A person's record from invitation to leaving: provisioning, profile, suspension and the leaver
path every deactivation shares (F14, FR-F14-006, FR-F14-007, FR-F14-012)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from django.db import transaction

from apps.accounts.models import Assignment, AuthSource, PersonStatus, User, UserRole
from apps.accounts.utils import sessions
from apps.accounts.utils.access import Access
from apps.accounts.utils.departments import departments
from apps.accounts.utils.grants import grants, locked_user, require_reason
from apps.accounts.utils.vocabulary import EndReason, OrgError, OrgRefusal
from apps.audit.models import AuditLog

PROFILE_FIELDS = ("first_name", "last_name", "job_title", "location", "phone", "employee_id")


@dataclass(frozen=True)
class Profile:
    """A person's profile; None leaves a field as it is. `line_manager` "" clears it."""

    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    location: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    department: str | None = None
    line_manager: str | None = None


class People:
    """Creates people ahead of their first sign-in, edits them, and takes them through
    suspension, return and leaving, each audited with a reason."""

    def provision(
        self, actor: User | None, username: str, email: str, profile: Profile, reason: str
    ) -> User:
        """An `invited` employee who links to their Keycloak identity on first sign-in by
        verified email (BR-F14-12)."""
        reason = require_reason(reason)
        username, email = username.strip(), email.strip().lower()
        with transaction.atomic():
            if User.objects.filter(username=username).exists():
                raise OrgError(409, OrgRefusal.USERNAME_TAKEN, f"{username} is taken")
            if User.objects.filter(email__iexact=email).exists():
                raise OrgError(409, OrgRefusal.EMAIL_TAKEN, f"{email} belongs to someone")
            user = User.objects.create_user(
                username=username,
                email=email,
                role=UserRole.EMPLOYEE.value,
                auth_source=AuthSource.OIDC.value,
                status=PersonStatus.INVITED.value,
                department=departments.default(),
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            self.apply_profile(actor, user, profile, reason)
            self.audit("person_provisioned", actor, user, {"email": email, "reason": reason})
        return user

    def update(self, actor: User | None, username: str, profile: Profile, reason: str) -> User:
        reason = require_reason(reason)
        with transaction.atomic():
            user = locked_user(username)
            before = self.snapshot(user)
            self.apply_profile(actor, user, profile, reason)
            after = self.snapshot(user)
            if before != after:
                self.audit(
                    "person_changed",
                    actor,
                    user,
                    {"before": before, "after": after, "reason": reason},
                )
        return user

    def apply_profile(self, actor: User | None, user: User, profile: Profile, reason: str) -> None:
        changed = []
        for name in PROFILE_FIELDS:
            value = getattr(profile, name)
            if value is not None and getattr(user, name) != value.strip():
                setattr(user, name, value.strip())
                changed.append(name)
        if profile.line_manager is not None:
            manager = None
            if profile.line_manager:
                manager = User.objects.filter(username=profile.line_manager).first()
                if manager is None or manager.pk == user.pk or self.manages(user, manager):
                    raise OrgError(
                        422,
                        OrgRefusal.LINE_MANAGER_INVALID,
                        f"{profile.line_manager!r} can't be {user.username}'s line manager",
                    )
            if user.line_manager_id != (manager.pk if manager else None):
                user.line_manager = manager
                changed.append("line_manager")
        if changed:
            user.save(update_fields=changed)
        if profile.department:
            departments.place(actor, user, departments.live(profile.department), reason)

    def manages(self, user: User, candidate: User) -> bool:
        """Whether `user` is somewhere above `candidate` in the line-manager chain."""
        seen, current = set(), candidate.line_manager_id
        while current is not None and current not in seen:
            if current == user.pk:
                return True
            seen.add(current)
            current = (
                User.objects.filter(pk=current).values_list("line_manager_id", flat=True).first()
            )
        return False

    # ── status ──

    def suspend(self, actor: User, username: str, reason: str) -> User:
        """Stops a person signing in while keeping their grants and teams."""
        reason = require_reason(reason)
        with transaction.atomic():
            user = locked_user(username)
            self.check_change(actor, user)
            if user.status == PersonStatus.SUSPENDED.value:
                raise OrgError(409, OrgRefusal.STATUS_UNCHANGED, f"{username} is suspended")
            grants.check_not_last_admin(user)
            self.set_status(actor, user, PersonStatus.SUSPENDED, reason, active=False)
            sessions.revoke_user(user, "suspended")
        return user

    def reactivate(self, actor: User, username: str, reason: str) -> User:
        """Lets a suspended or departed person sign in again; a leaver's grants stay ended."""
        reason = require_reason(reason)
        with transaction.atomic():
            user = locked_user(username)
            self.check_change(actor, user)
            if user.status in (PersonStatus.ACTIVE.value, PersonStatus.INVITED.value):
                raise OrgError(409, OrgRefusal.STATUS_UNCHANGED, f"{username} is {user.status}")
            status = (
                PersonStatus.ACTIVE
                if user.external_id or user.has_usable_password()
                else (PersonStatus.INVITED)
            )
            self.set_status(actor, user, status, reason, active=True)
        return user

    def deactivate(self, actor: User | None, username: str, reason: str) -> User:
        """The leaver path: sign-ins, grants, teams, headships and open tickets all end at once
        (BR-F14-14); a person in the console can't remove the last access admin."""
        reason = require_reason(reason)
        with transaction.atomic():
            user = locked_user(username)
            if actor is not None:
                self.check_change(actor, user)
                grants.check_not_last_admin(user)
            self.leave(actor, user, reason)
        return user

    def leave(self, actor: User | None, user: User, reason: str) -> dict[str, Any]:
        """Ends everything `user` holds; the identity sync calls this for a Keycloak leaver."""
        from apps.teams.models import TeamMembership
        from apps.teams.utils.config import team_config

        if user.status == PersonStatus.DEACTIVATED.value and not user.is_active:
            return {}
        for department in user.headed_departments.filter(archived_at__isnull=True):
            departments.set_head(actor, department, "")
        teams = []
        for membership in TeamMembership.objects.filter(user=user).select_related("team"):
            teams.append(membership.team.slug)
            team_config.leave(actor, membership, reason)
        ended = grants.end_rows(
            Assignment.objects.active().filter(user=user), EndReason.DEACTIVATED, actor, reason
        )
        tickets = self.release_tickets(actor, user)
        self.set_status(actor, user, PersonStatus.DEACTIVATED, reason, active=False)
        sessions.revoke_user(user, "deactivated")
        summary = {"teams": teams, "grants": ended, "tickets": tickets}
        self.audit("person_left", actor, user, {**summary, "reason": reason})
        return summary

    def release_tickets(self, actor: User | None, user: User) -> list[str]:
        """Puts the leaver's open tickets back in their team's queue, telling its lead."""
        from apps.lifecycle.utils.vocabulary import StatusKind
        from apps.teams.models import Team
        from apps.teams.utils.assignment import assignment
        from apps.tickets.models import Ticket

        released = []
        open_tickets = (
            Ticket.objects.select_for_update(of=("self",))
            .filter(assigned_to=user, resolved_at__isnull=True)
            .exclude(workflow_status__kind=StatusKind.COMPLETED.value)
            .select_related("team")
        )
        for ticket in open_tickets:
            team = ticket.team or Team.objects.fallback()
            if team is None:
                continue
            assignment.place(
                ticket,
                team,
                None,
                actor=actor,
                event="ticket_unassigned",
                payload={"reason": "assignee_left"},
            )
            released.append(ticket.public_id)
        return released

    def check_change(self, actor: User, user: User) -> None:
        if user.pk == actor.pk:
            raise OrgError(403, OrgRefusal.OWN_RIGHTS, "another person changes your account")
        if user.is_break_glass:
            raise OrgError(
                409, OrgRefusal.BREAK_GLASS_FIXED, "a break-glass account is changed in config"
            )

    def set_status(
        self, actor: User | None, user: User, status: PersonStatus, reason: str, *, active: bool
    ) -> None:
        before = user.status
        User.objects.filter(pk=user.pk).update(status=status.value, is_active=active)
        user.refresh_from_db(fields=["status", "is_active"])
        Access.forget(user)
        self.audit(
            "person_status_changed",
            actor,
            user,
            {"from": before, "to": status.value, "reason": reason},
        )

    def mark_signed_in(self, user: User) -> None:
        """An invited person becomes active at their first sign-in."""
        if user.status == PersonStatus.INVITED.value:
            User.objects.filter(pk=user.pk).update(status=PersonStatus.ACTIVE.value)
            user.refresh_from_db(fields=["status"])
            self.audit("person_status_changed", None, user, {"from": "invited", "to": "active"})

    def snapshot(self, user: User) -> dict[str, Any]:
        return {
            **{name: getattr(user, name) for name in PROFILE_FIELDS},
            "department": user.department.code if user.department else None,
            "line_manager": user.line_manager.username if user.line_manager else None,
        }

    def audit(self, event: str, actor: User | None, user: User, payload: dict[str, Any]) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human" if actor else "system",
            actor_id=actor.id if actor else None,
            payload={"user": user.username, **payload},
        )


PROFILE_KEYS = tuple(f.name for f in fields(Profile))

# --- the people service ---

people = People()
