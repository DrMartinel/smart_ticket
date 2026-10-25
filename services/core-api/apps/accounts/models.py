"""
Custom user model with an explicit role. RBAC decisions throughout
core-api key off `User.role`, not off Django's generic permission system —
the roles here map directly onto spec concepts (Employee / Technician /
Manager / Security) rather than a general-purpose permission matrix.
"""

from __future__ import annotations

import uuid
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


class User(AbstractUser, BaseModel):
    role = models.CharField(
        max_length=20,
        choices=[(r.value, r.value) for r in UserRole],
        default=UserRole.EMPLOYEE.value,
    )

    class Meta(BaseModel.Meta):
        db_table = "accounts_user"

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
