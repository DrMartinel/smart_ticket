"""People, their departments, roles and grants (F13, F14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar
from enum import StrEnum

from django.contrib.auth.models import AbstractUser, UserManager
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


class PersonStatus(StrEnum):
    """Where a person is in their lifecycle (F14 §c)."""

    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class Language(StrEnum):
    VI = "vi"
    EN = "en"


class UserQuerySet(models.QuerySet["User"]):
    def support_staff(self) -> UserQuerySet:
        """Active technicians, managers and security staff."""
        return self.filter(
            is_active=True,
            role__in=[UserRole.TECHNICIAN.value, UserRole.MANAGER.value, UserRole.SECURITY.value],
        )

    def with_capability(self, capability: str) -> UserQuerySet:
        """Active people who hold the add-on role for `capability` everywhere."""
        from apps.accounts.utils.catalog import ADD_ON_ROLES

        now = timezone.now()
        urn = ADD_ON_ROLES[Capability(capability)].value
        return (
            self.filter(
                is_active=True,
                assignments__role__urn=urn,
                assignments__scope_kind="global",
                assignments__ended_at__isnull=True,
                assignments__starts_at__lte=now,
            )
            .filter(
                models.Q(assignments__ends_at__isnull=True) | models.Q(assignments__ends_at__gt=now)
            )
            .distinct()
        )


class StaffUserManager(UserManager.from_queryset(UserQuerySet)):  # type: ignore[misc]
    pass


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
    failed_logins = models.PositiveIntegerField(default=0)
    last_failed_login_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    language = models.CharField(
        max_length=5, choices=[(lang.value, lang.value) for lang in Language], default="vi"
    )
    status = models.CharField(
        max_length=12,
        choices=[(s.value, s.value) for s in PersonStatus],
        default=PersonStatus.ACTIVE.value,
    )
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="people",
    )
    line_manager = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )
    job_title = models.CharField(max_length=120, blank=True, default="")
    location = models.CharField(max_length=120, blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    employee_id = models.CharField(max_length=40, blank=True, default="")

    objects: ClassVar[StaffUserManager] = StaffUserManager()

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

    def capability_set(self) -> frozenset[str]:
        """The add-on roles the user holds everywhere, named as capabilities (ADR-0031)."""
        from apps.accounts.utils.catalog import ADD_ON_ROLES

        by_urn = {urn.value: capability.value for capability, urn in ADD_ON_ROLES.items()}
        now = timezone.now()
        return frozenset(
            by_urn[a.role.urn]
            for a in self.assignments.all()
            if a.role.urn in by_urn and a.scope_kind == "global" and a.is_active_at(now)
        )

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


class DepartmentQuerySet(models.QuerySet["Department"]):
    def live(self) -> DepartmentQuerySet:
        return self.filter(archived_at__isnull=True)


class Department(BaseModel):
    """One unit of the organisation the people who ask for help belong to (F14)."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    head = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="headed_departments"
    )
    cost_centre = models.CharField(max_length=40, blank=True, default="")
    is_default = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    objects = DepartmentQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "acc_departments"
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="acc_departments_one_default",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class RoleQuerySet(models.QuerySet["Role"]):
    def live(self) -> RoleQuerySet:
        return self.filter(retired_at__isnull=True)


class Role(BaseModel):
    """A named set of permissions, granted to people with a scope (ADR-0045)."""

    urn = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    is_system = models.BooleanField(default=False)
    # A department head may grant it within their subtree (FR-F14-009).
    delegable = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    objects = RoleQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "acc_roles"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    urn__regex=r"^urn:smart-ticket:role:(system|custom):[a-z][a-z0-9-]{1,47}$"
                ),
                name="acc_roles_urn_format",
            ),
            models.CheckConstraint(
                condition=models.Q(is_system=True, urn__startswith="urn:smart-ticket:role:system:")
                | models.Q(is_system=False, urn__startswith="urn:smart-ticket:role:custom:"),
                name="acc_roles_urn_kind_matches",
            ),
        ]

    def __str__(self) -> str:
        return self.urn


class RolePermission(BaseModel):
    """One permission in a custom role; system roles keep theirs in code."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permission_rows")
    permission_urn = models.CharField(max_length=120)

    class Meta(BaseModel.Meta):
        db_table = "acc_role_permissions"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission_urn"], name="uniq_role_permission"),
            models.CheckConstraint(
                condition=models.Q(
                    permission_urn__regex=r"^urn:smart-ticket:perm:[a-z][a-z0-9-]{0,31}(:[a-z][a-z0-9-]{0,31}){1,2}$"
                ),
                name="acc_role_permissions_urn_format",
            ),
        ]


class AssignmentSource(StrEnum):
    """Why a grant exists."""

    MANUAL = "manual"
    STRUCTURAL = "structural"
    MIGRATED = "migrated"


class AssignmentQuerySet(models.QuerySet["Assignment"]):
    def active(self, now: datetime | None = None) -> AssignmentQuerySet:
        """Grants that apply at `now`: started, not ended, not past their end date."""
        now = now or timezone.now()
        return self.filter(ended_at__isnull=True, starts_at__lte=now).filter(
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now)
        )


class Assignment(BaseModel):
    """One role granted to one person at one scope (BR-F14-03)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    scope_kind = models.CharField(max_length=12, default="global")
    scope_team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    scope_department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    source = models.CharField(
        max_length=12,
        choices=[(s.value, s.value) for s in AssignmentSource],
        default=AssignmentSource.MANUAL.value,
    )
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.CharField(max_length=500, blank=True, default="")
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=40, blank=True, default="")
    needs_review = models.BooleanField(default=False)
    review_due_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    expiry_noticed_at = models.DateTimeField(null=True, blank=True)

    objects = AssignmentQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "acc_assignments"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope_kind="global", scope_team__isnull=True, scope_department__isnull=True
                    )
                    | models.Q(
                        scope_kind="team", scope_team__isnull=False, scope_department__isnull=True
                    )
                    | models.Q(
                        scope_kind="department",
                        scope_team__isnull=True,
                        scope_department__isnull=False,
                    )
                ),
                name="acc_assignments_one_scope",
            ),
        ]
        indexes = [models.Index(fields=["user", "ended_at"], name="acc_assignments_user_live")]

    def is_active_at(self, now: datetime) -> bool:
        return (
            self.ended_at is None
            and self.starts_at <= now
            and (self.ends_at is None or self.ends_at > now)
        )

    def scope_label(self) -> str:
        """The scope as `global`, `team:<slug>` or `department:<code>`."""
        if self.scope_kind == "team" and self.scope_team is not None:
            return f"team:{self.scope_team.slug}"
        if self.scope_kind == "department" and self.scope_department is not None:
            return f"department:{self.scope_department.code}"
        return "global"


class ReviewCampaignState(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class NoAnswer(StrEnum):
    """What closing a campaign does to a grant nobody answered for."""

    REVOKE = "revoke"
    FLAG = "flag"


class AccessReviewCampaign(BaseModel):
    """One access review over a set of grants (UC-F14-07)."""

    name = models.CharField(max_length=120)
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    on_no_answer = models.CharField(
        max_length=10, choices=[(n.value, n.value) for n in NoAnswer], default=NoAnswer.FLAG.value
    )
    fallback_reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    state = models.CharField(
        max_length=10,
        choices=[(s.value, s.value) for s in ReviewCampaignState],
        default=ReviewCampaignState.OPEN.value,
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField(auto_now_add=True)
    closes_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "acc_review_campaigns"


class ReviewDecisionKind(StrEnum):
    KEEP = "keep"
    REVOKE = "revoke"


class AccessReviewItemQuerySet(models.QuerySet["AccessReviewItem"]):
    def pending(self) -> AccessReviewItemQuerySet:
        return self.filter(decision="", campaign__state=ReviewCampaignState.OPEN.value)


class AccessReviewItem(BaseModel):
    """One grant in a campaign and its reviewer's answer."""

    campaign = models.ForeignKey(
        AccessReviewCampaign, on_delete=models.CASCADE, related_name="items"
    )
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="+")
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=10, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)

    objects = AccessReviewItemQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "acc_review_items"
        constraints = [
            models.UniqueConstraint(fields=["campaign", "assignment"], name="uniq_review_item")
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


class RefusedCallQuerySet(models.QuerySet["RefusedCall"]):
    def since(self, at: datetime) -> RefusedCallQuerySet:
        return self.filter(at__gte=at)


class RefusedCall(BaseModel):
    """One call a role gate refused, kept a day for burst detection (F8 BR-F8-08)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    route = models.CharField(max_length=200)
    at = models.DateTimeField(auto_now_add=True)

    objects = RefusedCallQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "accounts_refused_calls"
        indexes = [models.Index(fields=["at", "user"], name="accounts_refused_at_user")]
