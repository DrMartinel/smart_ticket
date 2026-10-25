"""
Custom user model with an explicit role. RBAC decisions throughout
core-api key off `User.role`, not off Django's generic permission system —
the roles here map directly onto spec concepts (Employee / Technician /
Manager / Security) rather than a general-purpose permission matrix.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class UserRole(StrEnum):
    EMPLOYEE = "employee"
    TECHNICIAN = "technician"
    MANAGER = "manager"
    SECURITY = "security"


class AuthSource(StrEnum):
    """Where a user's identity and rights come from (F13)."""

    LOCAL = "local"
    OIDC = "oidc"


class Capability(StrEnum):
    """Rights on top of the primary role (ADR-0031)."""

    WORKFLOW_ADMIN = "workflow_admin"
    KB_EDITOR = "kb_editor"
    INCIDENT_MANAGER = "incident_manager"


class Language(StrEnum):
    VI = "vi"
    EN = "en"


class User(AbstractUser, BaseModel):
    role = models.CharField(
        max_length=20,
        choices=[(r.value, r.value) for r in UserRole],
        default=UserRole.EMPLOYEE.value,
    )
    external_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    auth_source = models.CharField(
        max_length=10,
        choices=[(s.value, s.value) for s in AuthSource],
        default=AuthSource.LOCAL.value,
    )
    is_break_glass = models.BooleanField(default=False)
    rights_synced_at = models.DateTimeField(null=True, blank=True)
    failed_logins = models.PositiveIntegerField(default=0)
    last_failed_login_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    language = models.CharField(
        max_length=5, choices=[(lang.value, lang.value) for lang in Language], default="vi"
    )

    class Meta(BaseModel.Meta):
        db_table = "accounts_user"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_break_glass=False) | models.Q(role="manager"),
                name="accounts_user_break_glass_is_manager",
            )
        ]

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"

    @property
    def is_manager(self) -> bool:
        return self.role == UserRole.MANAGER.value

    @property
    def is_technician(self) -> bool:
        return self.role == UserRole.TECHNICIAN.value

    @property
    def is_security(self) -> bool:
        return self.role == UserRole.SECURITY.value

    def capability_set(self) -> frozenset[str]:
        """The user's capabilities; reads the prefetched rows when there are any."""
        return frozenset(c.capability for c in self.capabilities.all())

    def is_locked(self, now: datetime) -> bool:
        """Whether local sign-in is locked after too many failed passwords."""
        return self.locked_until is not None and self.locked_until > now

    @property
    def is_support_staff(self) -> bool:
        """Whether the user works tickets: technician, manager or security."""
        return self.role in (
            UserRole.TECHNICIAN.value,
            UserRole.MANAGER.value,
            UserRole.SECURITY.value,
        )

    @property
    def may_run_runbooks(self) -> bool:
        """Whether the user may approve or execute a runbook (ADR-0006, FR-PRE1-005)."""
        return self.role in (UserRole.TECHNICIAN.value, UserRole.MANAGER.value)


class AuthClient(StrEnum):
    """The frontends a refresh session belongs to; each keeps its own cookie."""

    ADMIN = "admin"
    CHAT = "chat"


class RefreshSessionQuerySet(models.QuerySet["RefreshSession"]):
    def live_family(self, family: uuid.UUID | str) -> RefreshSessionQuerySet:
        """The family's sessions that are neither revoked nor expired."""
        return self.filter(family=family, revoked_at__isnull=True, expires_at__gt=timezone.now())


class RefreshSession(BaseModel):
    """One refresh token. Each rotation adds a row to its login's family; only the hash is stored."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_sessions")
    client = models.CharField(max_length=10, choices=[(c.value, c.value) for c in AuthClient])
    family = models.UUIDField(db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    family_expires_at = models.DateTimeField()
    rotated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=40, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = RefreshSessionQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "accounts_refresh_sessions"


class UserCapability(BaseModel):
    """One capability granted to a user (ADR-0031)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="capabilities")
    capability = models.CharField(max_length=30, choices=[(c.value, c.value) for c in Capability])
    source = models.CharField(max_length=10, choices=[("keycloak", "keycloak"), ("local", "local")])
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "accounts_user_capabilities"
        constraints = [
            models.UniqueConstraint(fields=["user", "capability"], name="uniq_user_capability")
        ]


class IdentitySyncRunQuerySet(models.QuerySet["IdentitySyncRun"]):
    def failures_in_a_row(self) -> int:
        """Failed runs since the last successful one."""
        count = 0
        for ok in self.order_by("-started_at").values_list("ok", flat=True)[:50]:
            if ok:
                break
            count += 1
        return count


class IdentitySyncRun(BaseModel):
    """One run of the Keycloak sync task (F13)."""

    started_at = models.DateTimeField(auto_now_add=True)
    ok = models.BooleanField()
    checked = models.PositiveIntegerField(default=0)
    changed = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True, default="")

    objects = IdentitySyncRunQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "accounts_identity_sync_runs"
