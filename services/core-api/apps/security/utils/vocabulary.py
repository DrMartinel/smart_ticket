"""The security inbox's kinds, severities, states and refusals (F8)."""

from __future__ import annotations

from enum import StrEnum

from apps.core.errors import CodedError


class AlertKind(StrEnum):
    PII_CRITICAL = "pii_critical"
    CREDENTIAL_IN_REPLY = "credential_in_reply"
    REFRESH_TOKEN_REUSED = "refresh_token_reused"
    BREAK_GLASS_SIGN_IN = "break_glass_sign_in"
    BREAK_GLASS_IN_KEYCLOAK = "break_glass_in_keycloak"
    INJECTION_DETECTED = "injection_detected"
    AMBIGUOUS_ROLE = "ambiguous_role"
    REVEAL_RATE_LIMITED = "reveal_rate_limited"
    DECRYPT_FAILED = "decrypt_failed"
    REVEAL_FAILED = "reveal_failed"
    ACCESS_DENIED_BURST = "access_denied_burst"
    THRESHOLDS_UNAPPROVED = "thresholds_unapproved"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


# BR-F8 §e's table, plus the two kinds the build found writers for.
SEVERITY = {
    AlertKind.PII_CRITICAL: Severity.CRITICAL,
    AlertKind.CREDENTIAL_IN_REPLY: Severity.CRITICAL,
    AlertKind.REFRESH_TOKEN_REUSED: Severity.CRITICAL,
    AlertKind.BREAK_GLASS_SIGN_IN: Severity.CRITICAL,
    AlertKind.BREAK_GLASS_IN_KEYCLOAK: Severity.CRITICAL,
    AlertKind.INJECTION_DETECTED: Severity.HIGH,
    AlertKind.AMBIGUOUS_ROLE: Severity.HIGH,
    AlertKind.REVEAL_RATE_LIMITED: Severity.HIGH,
    AlertKind.DECRYPT_FAILED: Severity.HIGH,
    AlertKind.REVEAL_FAILED: Severity.HIGH,
    AlertKind.ACCESS_DENIED_BURST: Severity.MEDIUM,
    AlertKind.THRESHOLDS_UNAPPROVED: Severity.HIGH,
}

# Kinds whose alert can tell the requester to change a credential (UC-F8-02).
CREDENTIAL_KINDS = frozenset({AlertKind.PII_CRITICAL, AlertKind.CREDENTIAL_IN_REPLY})

# Most urgent first, for sorting.
SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2}


class AlertState(StrEnum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    CLOSED = "closed"


OPEN_ALERT_STATES = (AlertState.NEW, AlertState.ACKNOWLEDGED, AlertState.INVESTIGATING)


class Resolution(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    DUPLICATE = "duplicate"


class EventKind(StrEnum):
    RAISED = "raised"
    REGROUPED = "regrouped"
    ACK = "ack"
    NOTE = "note"
    STATE = "state"
    RELEASE = "release"
    NOTIFIED = "notified"


class SecurityRefusal(StrEnum):
    NOT_FOUND = "alert_not_found"
    NOT_NEW = "not_new"
    NOT_SECURITY = "not_security"
    NOTE_REQUIRED = "note_required"
    REASON_REQUIRED = "reason_required"
    NOT_CLOSED = "not_closed"
    ALREADY_CLOSED = "already_closed"
    NOT_BLOCKED = "not_blocked"
    NO_TICKET = "no_ticket"
    NO_USER = "no_user"
    NOT_A_CREDENTIAL = "not_a_credential"
    DUPLICATE_REQUIRED = "duplicate_required"


class SecurityError(CodedError):
    """A security inbox request core-api refuses."""
