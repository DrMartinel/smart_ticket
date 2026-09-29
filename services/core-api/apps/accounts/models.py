"""
Custom user model with an explicit role. RBAC decisions throughout
core-api key off `User.role`, not off Django's generic permission system —
the roles here map directly onto spec concepts (Employee / Technician /
Manager / Security) rather than a general-purpose permission matrix.
"""

import uuid
from enum import StrEnum

from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(StrEnum):
    EMPLOYEE = "employee"
    TECHNICIAN = "technician"
    MANAGER = "manager"
    SECURITY = "security"


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    role = models.CharField(
        max_length=20,
        choices=[(r.value, r.value) for r in UserRole],
        default=UserRole.EMPLOYEE.value,
    )

    class Meta:
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
