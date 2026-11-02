"""Assignment's triggers, reassignment reasons and refusal codes (F2)."""

from __future__ import annotations

from enum import StrEnum


class AssignmentTrigger(StrEnum):
    """What handed a ticket to a team."""

    AUTO_ROUTE = "auto_route"
    REVIEW = "review"
    RELEASE = "release"
    ACTION = "action"
    TAKE = "take"
    REASSIGN = "reassign"


class ReassignReason(StrEnum):
    WRONG_TEAM = "wrong_team"
    WORKLOAD = "workload"
    SKILL = "skill"
    LEAVE = "leave"
    ESCALATION = "escalation"
    REQUESTER_REQUEST = "requester_request"
    OTHER = "other"


class AssignmentFailure(StrEnum):
    """Why assignment at handoff fell short, in `assignment_failed` audit rows."""

    NO_TEAM_FOR_CATEGORY = "no_team_for_category"
    NO_CATEGORY = "no_category"
    NO_FALLBACK_TEAM = "no_fallback_team"
    ERROR = "error"


class TeamRefusal(StrEnum):
    NOT_A_MEMBER = "not_a_member"
    ALREADY_ASSIGNED = "already_assigned"
    LEAD_REQUIRED = "lead_required"
    REASON_REQUIRED = "reason_required"
    VERSION_CONFLICT = "version_conflict"
    CATEGORY_TAKEN = "category_taken"
    CATEGORY_UNOWNED = "category_unowned"
    CATEGORY_REQUIRED = "category_required"
    BAD_DATES = "bad_dates"
    TEAM_NOT_FOUND = "team_not_found"
    USER_NOT_IN_TEAM = "user_not_in_team"
    TICKET_COMPLETED = "ticket_completed"
    FALLBACK_REQUIRED = "fallback_required"
    MANAGED_BY_KEYCLOAK = "managed_by_keycloak"
    LEAVE_NOT_FOUND = "leave_not_found"
    NOT_ALLOWED = "not_allowed"
    TICKET_NOT_FOUND = "ticket_not_found"
