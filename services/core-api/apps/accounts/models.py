"""
Custom user model with an explicit role. RBAC decisions throughout
core-api key off `User.role`, not off Django's generic permission system —
the roles here map directly onto spec concepts (Employee / Technician /
Manager / Security) rather than a general-purpose permission matrix.
"""

from enum import StrEnum
from typing import ClassVar

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from apps.core.models import BaseModel


class UserRole(StrEnum):
    EMPLOYEE = "employee"
    TECHNICIAN = "technician"
    MANAGER = "manager"
    SECURITY = "security"


class User(AbstractUser, BaseModel):
    # Same manager AbstractUser already sets; declared so pyright can
    # reconcile it with BaseModel's default `objects`.
    objects: ClassVar[UserManager["User"]] = UserManager()  # pyright: ignore[reportIncompatibleVariableOverride]

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
