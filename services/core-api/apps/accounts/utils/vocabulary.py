"""Refusal codes of the people, department, role, grant and review services (F14)."""

from __future__ import annotations

from enum import StrEnum

from apps.core.errors import CodedError


class OrgRefusal(StrEnum):
    REASON_REQUIRED = "reason_required"
    USER_NOT_FOUND = "user_not_found"
    USER_INACTIVE = "user_inactive"
    OWN_RIGHTS = "own_rights"
    BREAK_GLASS_FIXED = "break_glass_fixed"
    LAST_ACCESS_ADMIN = "last_access_admin"
    ROLE_NOT_FOUND = "role_not_found"
    ROLE_NAME_INVALID = "role_name_invalid"
    ROLE_URN_TAKEN = "role_urn_taken"
    ROLE_IS_SYSTEM = "role_is_system"
    ROLE_RETIRED = "role_retired"
    ROLE_IS_BASE = "role_is_base"
    ROLE_IS_STRUCTURAL = "role_is_structural"
    PERMISSIONS_REQUIRED = "permissions_required"
    PERMISSION_UNKNOWN = "permission_unknown"
    PERMISSION_LOCKED = "permission_locked"
    CANNOT_GRANT_UNHELD = "cannot_grant_unheld"
    STAFF_ONLY = "staff_only"
    SCOPE_NOT_ALLOWED = "scope_not_allowed"
    SCOPE_TARGET_NOT_FOUND = "scope_target_not_found"
    GRANT_NOT_FOUND = "grant_not_found"
    GRANT_EXISTS = "grant_exists"
    GRANT_ENDED = "grant_ended"
    GRANT_IS_STRUCTURAL = "grant_is_structural"
    ENDS_BEFORE_START = "ends_before_start"
    DEPARTMENT_NOT_FOUND = "department_not_found"
    DEPARTMENT_CODE_INVALID = "department_code_invalid"
    DEPARTMENT_CODE_TAKEN = "department_code_taken"
    DEPARTMENT_NAME_REQUIRED = "department_name_required"
    DEPARTMENT_CYCLE = "department_cycle"
    DEPARTMENT_TOO_DEEP = "department_too_deep"
    DEPARTMENT_NOT_EMPTY = "department_not_empty"
    DEPARTMENT_IS_DEFAULT = "department_is_default"
    DEPARTMENT_ARCHIVED = "department_archived"
    USERNAME_TAKEN = "username_taken"
    EMAIL_TAKEN = "email_taken"
    LINE_MANAGER_INVALID = "line_manager_invalid"
    STATUS_UNCHANGED = "status_unchanged"
    IMPORT_TOO_LARGE = "import_too_large"
    IMPORT_INVALID = "import_invalid"
    REVIEW_NOT_FOUND = "review_not_found"
    REVIEW_CLOSED = "review_closed"
    REVIEW_EMPTY = "review_empty"
    REVIEW_DECIDED = "review_decided"
    NOT_YOUR_REVIEW = "not_your_review"
    FALLBACK_CANNOT_REVIEW = "fallback_cannot_review"
    NO_OTHER_REVIEWER = "no_other_reviewer"


class OrgError(CodedError):
    """A people, department, role, grant or review change core-api refuses."""

    code: OrgRefusal


class EndReason(StrEnum):
    """Why a grant ended, on `acc_assignments.ended_reason`."""

    ENDED = "ended"
    EXPIRED = "expired"
    RIGHTS_CHANGED = "rights_changed"
    BECAME_EMPLOYEE = "became_employee"
    LEFT_TEAM = "left_team"
    NO_LONGER_LEAD = "no_longer_lead"
    NO_LONGER_HEAD = "no_longer_head"
    ROLE_RETIRED = "role_retired"
    DEPARTMENT_ARCHIVED = "department_archived"
    MOVER_UNCONFIRMED = "mover_unconfirmed"
    REVIEW_REVOKED = "review_revoked"
    REVIEW_NO_ANSWER = "review_no_answer"
    DEACTIVATED = "deactivated"
