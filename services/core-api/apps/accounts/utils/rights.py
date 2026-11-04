"""A person's role and capabilities, set by a manager in the console (ADR-0042)."""

from __future__ import annotations

from enum import StrEnum

from django.db import transaction

from apps.accounts.models import Capability, User, UserCapability, UserRole
from apps.accounts.utils import sessions
from apps.audit.models import AuditLog
from apps.core.errors import CodedError


class RightsRefusal(StrEnum):
    USER_NOT_FOUND = "user_not_found"
    OWN_RIGHTS = "own_rights"
    BREAK_GLASS_FIXED = "break_glass_fixed"
    CAPABILITY_NEEDS_STAFF = "capability_needs_staff"
    HAS_OPEN_TICKETS = "has_open_tickets"
    REASON_REQUIRED = "reason_required"


class RightsError(CodedError):
    """A role or capability change core-api refuses."""


class AccountRights:
    """Changes who may do what, ending the person's sign-ins so the change applies at once."""

    def assign(
        self,
        actor: User,
        username: str,
        role: UserRole,
        capabilities: set[Capability],
        reason: str,
    ) -> User:
        """Sets `username`'s role and capabilities; an employee leaves every team."""
        from apps.teams.models import TeamMembership

        if not reason.strip():
            raise RightsError(422, RightsRefusal.REASON_REQUIRED, "say why the rights change")
        with transaction.atomic():
            user = User.objects.select_for_update().filter(username=username).first()
            if user is None:
                raise RightsError(404, RightsRefusal.USER_NOT_FOUND, f"no user {username!r}")
            before = {"role": user.role, "capabilities": sorted(user.capability_set())}
            after = {"role": role.value, "capabilities": sorted(c.value for c in capabilities)}
            if before == after:
                return user
            self.check(actor, user, role, capabilities)
            left = []
            if role is UserRole.EMPLOYEE:
                memberships = TeamMembership.objects.filter(user=user).select_related("team")
                left = sorted(m.team.slug for m in memberships)
                memberships.delete()
            user.role = role.value
            user.save(update_fields=["role"])
            UserCapability.objects.filter(user=user).exclude(
                capability__in=after["capabilities"]
            ).delete()
            for capability in capabilities:
                UserCapability.objects.get_or_create(user=user, capability=capability.value)
            sessions.revoke_user(user, "rights_changed")
            AuditLog.objects.record(
                "rights_changed",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "user": user.username,
                    "before": before,
                    "after": after,
                    "left_teams": left,
                    "reason": reason.strip(),
                },
            )
        return user

    def check(self, actor: User, user: User, role: UserRole, capabilities: set[Capability]) -> None:
        """The rules every change keeps: never your own, break-glass stays a manager,
        staff-only capabilities, and no employee with open work."""
        from apps.lifecycle.utils.vocabulary import StatusKind
        from apps.tickets.models import Ticket

        if user.pk == actor.pk:
            raise RightsError(403, RightsRefusal.OWN_RIGHTS, "another manager changes your rights")
        if user.is_break_glass and role is not UserRole.MANAGER:
            raise RightsError(
                409, RightsRefusal.BREAK_GLASS_FIXED, "a break-glass account stays a manager"
            )
        if role is UserRole.EMPLOYEE and capabilities:
            raise RightsError(
                422, RightsRefusal.CAPABILITY_NEEDS_STAFF, "an employee holds no capabilities"
            )
        if (
            role is UserRole.EMPLOYEE
            and Ticket.objects.filter(assigned_to=user, resolved_at__isnull=True)
            .exclude(workflow_status__kind=StatusKind.COMPLETED.value)
            .exists()
        ):
            raise RightsError(
                409,
                RightsRefusal.HAS_OPEN_TICKETS,
                f"reassign {user.username}'s open tickets first",
            )


# --- the rights service ---

account_rights = AccountRights()
