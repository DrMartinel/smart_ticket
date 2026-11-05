"""Custom roles: created, edited and retired with a reason; system roles stay as code made them."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Assignment, Role, RolePermission, User
from apps.accounts.utils.access import Access, role_permissions
from apps.accounts.utils.catalog import (
    PERMISSIONS,
    ROLE_URN,
    Permission,
    custom_role_urn,
)
from apps.accounts.utils.grants import grants, require_reason
from apps.accounts.utils.vocabulary import EndReason, OrgError, OrgRefusal
from apps.audit.models import AuditLog


@dataclass(frozen=True)
class RoleDraft:
    """A custom role's name, description and permissions; None leaves a field as it is."""

    name: str | None
    description: str | None
    permissions: list[str] | None
    reason: str


class Roles:
    """Creates, edits and retires custom roles (UC-F14-01, BR-F14-02, BR-F14-19)."""

    def create(self, actor: User, draft: RoleDraft) -> Role:
        """A new custom role under a URN made from its name, which never changes afterwards."""
        reason = require_reason(draft.reason)
        name = (draft.name or "").strip()
        urn = custom_role_urn(name)
        if not name or not ROLE_URN.match(urn):
            raise OrgError(
                422, OrgRefusal.ROLE_NAME_INVALID, "a role name needs two letters or digits"
            )
        permissions = self.checked(actor, draft.permissions or [], already=frozenset())
        with transaction.atomic():
            if Role.objects.filter(urn=urn).exists():
                raise OrgError(
                    409, OrgRefusal.ROLE_URN_TAKEN, f"{urn} is taken, perhaps by a retired role"
                )
            role = Role.objects.create(
                urn=urn, name=name, description=(draft.description or "").strip(), is_system=False
            )
            RolePermission.objects.bulk_create(
                RolePermission(role=role, permission_urn=p.value) for p in sorted(permissions)
            )
            self.audit(actor, role, "created", reason, added=permissions, removed=frozenset())
        return role

    def update(self, actor: User, urn: str, draft: RoleDraft) -> Role:
        """Renames a custom role or sets its permissions; the URN stays."""
        reason = require_reason(draft.reason)
        with transaction.atomic():
            role = self.editable(urn)
            before = role_permissions(role)
            after = before
            if draft.permissions is not None:
                after = self.checked(actor, draft.permissions, already=before)
            if draft.name is not None and draft.name.strip():
                role.name = draft.name.strip()
            if draft.description is not None:
                role.description = draft.description.strip()
            role.save(update_fields=["name", "description"])
            if after != before:
                RolePermission.objects.filter(role=role).exclude(
                    permission_urn__in=[p.value for p in after]
                ).delete()
                RolePermission.objects.bulk_create(
                    RolePermission(role=role, permission_urn=p.value)
                    for p in sorted(after - before)
                )
            self.audit(actor, role, "updated", reason, added=after - before, removed=before - after)
        return role

    def retire(self, actor: User, urn: str, reason: str) -> Role:
        """Retires a custom role and ends every grant of it; its URN is never reused."""
        reason = require_reason(reason)
        with transaction.atomic():
            role = self.editable(urn)
            role.retired_at = timezone.now()
            role.save(update_fields=["retired_at"])
            grants.end_rows(
                Assignment.objects.active().filter(role=role), EndReason.ROLE_RETIRED, actor, reason
            )
            self.audit(actor, role, "retired", reason, added=frozenset(), removed=frozenset())
        return role

    def checked(
        self, actor: User, wanted: list[str], *, already: frozenset[Permission]
    ) -> frozenset[Permission]:
        """The permissions named, refusing unknown and locked ones and any new one the actor
        doesn't hold everywhere (BR-F14-04, BR-F14-05)."""
        known = {p.value: p for p in Permission}
        unknown = sorted(u for u in wanted if u not in known)
        if unknown:
            raise OrgError(
                422, OrgRefusal.PERMISSION_UNKNOWN, "no such permission", {"permissions": unknown}
            )
        permissions = frozenset(known[u] for u in wanted)
        if not permissions:
            raise OrgError(422, OrgRefusal.PERMISSIONS_REQUIRED, "a role holds a permission")
        locked = sorted(p.value for p in permissions if PERMISSIONS[p].locked)
        if locked:
            raise OrgError(
                422,
                OrgRefusal.PERMISSION_LOCKED,
                "a locked permission comes only from a system role",
                {"permissions": locked},
            )
        access = Access.of(actor)
        unheld = sorted(p.value for p in permissions - already if not access.holds_everywhere(p))
        if unheld:
            raise OrgError(
                403,
                OrgRefusal.CANNOT_GRANT_UNHELD,
                "you can only add permissions you hold everywhere",
                {"permissions": unheld},
            )
        return permissions

    def editable(self, urn: str) -> Role:
        role = Role.objects.select_for_update().filter(urn=urn).first()
        if role is None:
            raise OrgError(404, OrgRefusal.ROLE_NOT_FOUND, f"no role {urn!r}")
        if role.is_system:
            raise OrgError(409, OrgRefusal.ROLE_IS_SYSTEM, "a system role is defined in code")
        if role.retired_at is not None:
            raise OrgError(409, OrgRefusal.ROLE_RETIRED, f"{urn} is retired")
        return role

    def audit(
        self,
        actor: User,
        role: Role,
        change: str,
        reason: str,
        *,
        added: frozenset[Permission],
        removed: frozenset[Permission],
    ) -> None:
        AuditLog.objects.record(
            "role_changed",
            actor_type="human",
            actor_id=actor.id,
            payload={
                "change": change,
                "role": role.urn,
                "name": role.name,
                "added": sorted(p.value for p in added),
                "removed": sorted(p.value for p in removed),
                "reason": reason,
            },
        )


# --- the roles service ---

roles = Roles()
