"""Rollout flags, gates, threshold change requests: their states and refusals (F9, ADR-0035)."""

from __future__ import annotations

from enum import StrEnum

from apps.core.errors import CodedError


class FlagBranch(StrEnum):
    """The automated branch families a flag turns live. None exists for runbooks (ADR-0006)."""

    AUTO_ROUTE = "auto_route"
    AUTO_REPLY = "auto_reply"
    REQUESTER_QUESTIONS = "requester_questions"


class FlagState(StrEnum):
    OFF = "off"
    PENDING_ON = "pending_on"
    ON = "on"


class RequestState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Comparator(StrEnum):
    LT = "lt"
    GTE = "gte"


class GateMetric(StrEnum):
    # Shadow auto_route decisions a reviewer rerouted ÷ those a reviewer decided.
    REROUTE_RATE = "reroute_rate"
    # Shadow clarify decisions a reviewer approved ÷ those a reviewer decided.
    CLARIFY_AGREEMENT = "clarify_agreement"
    # Active, approved, low-risk KB pages.
    APPROVED_LOW_PAGES = "approved_low_pages"
    # Auto-reply precision on the calibration holdout: entered with evidence, not computed.
    HOLDOUT_PRECISION = "holdout_precision"


# Gate values the requester enters, with evidence; the rest are computed (owner, 2026-10-26).
ENTERED_METRICS = frozenset({GateMetric.HOLDOUT_PRECISION})


class ChangeState(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    LOADED = "loaded"


# Change requests whose file may act on tickets.
APPROVED_CHANGE_STATES = (ChangeState.APPROVED, ChangeState.LOADED)


class RolloutRefusal(StrEnum):
    NO_SUCH_BRANCH = "no_such_branch"
    ALREADY_ON = "already_on"
    ALREADY_OFF = "already_off"
    ALREADY_REQUESTED = "already_requested"
    THRESHOLDS_UNAPPROVED = "thresholds_unapproved"
    SELF_APPROVAL = "self_approval"
    ALREADY_APPROVED_BY_YOU = "already_approved_by_you"
    OVERRIDE_REASON_REQUIRED = "override_reason_required"
    REASON_REQUIRED = "reason_required"
    NOT_PENDING = "not_pending"
    NOT_A_MANAGER = "not_a_manager"
    ENTERED_VALUE_REQUIRED = "entered_value_required"
    INVALID_THRESHOLDS = "invalid_thresholds"
    VERSION_MISMATCH = "version_mismatch"
    NOT_THE_AUTHOR = "not_the_author"
    NOT_FOUND = "not_found"


class RolloutError(CodedError):
    """A rollout or threshold request core-api refuses."""
