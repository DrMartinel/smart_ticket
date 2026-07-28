"""
Shared enums — spec §4.1.

`ReasonCode` in particular is a closed enum, never a free-text string. That
is what lets the dashboard answer "which reason pushed the most tickets to
HITL this week" with a GROUP BY instead of NLP over log lines.
"""

from enum import StrEnum


class TicketCategory(StrEnum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    ACCESS = "access"
    SECURITY = "security"
    OTHER = "other"


class PIILevel(StrEnum):
    ROUTINE = "routine"  # name, internal email, employee code → proceeds
    SENSITIVE = "sensitive"  # national ID, bank account, health → proceeds, flagged
    CRITICAL = "critical"  # password / token / API key → BLOCK
    MASK_FAILED = "mask_failed"  # masker errored / uncertain → HITL


class Branch(StrEnum):
    AUTO_REPLY = "auto_reply"
    AUTO_ROUTE = "auto_route"
    HITL = "hitl"
    BLOCK = "block"
    ESCALATE = "escalate"


class ReasonCode(StrEnum):
    # hard gates
    INJECTION_DETECTED = "injection_detected"
    PII_CRITICAL = "pii_critical"
    PII_MASK_FAILED = "pii_mask_failed"
    SCHEMA_INVALID = "schema_invalid"
    MASS_INCIDENT = "mass_incident"
    RETRIEVAL_FLOOR = "retrieval_below_floor"
    # trust-based
    KB_NOT_AUTHORIZED = "kb_not_authorized"
    QUOTE_INVALID = "quote_invalid"
    QUOTE_SOURCE_MISMATCH = "quote_source_not_in_topk"
    NEGATION_MISMATCH = "negation_mismatch"
    TRUST_BELOW_AUTO = "trust_below_auto_threshold"
    TRUST_BELOW_ROUTE = "trust_below_route_threshold"
    CATEGORY_INCONSISTENT = "category_inconsistent"
    # degraded
    AI_ENGINE_UNAVAILABLE = "ai_engine_unavailable"
    EMBEDDING_UNAVAILABLE = "embedding_unavailable"
    BUDGET_EXCEEDED = "budget_exceeded"
    CIRCUIT_OPEN = "circuit_open"
    # ok
    ALL_CHECKS_PASSED = "all_checks_passed"


class ReviewQueue(StrEnum):
    PII_VERIFY = "pii_verify"
    LOW_CONFIDENCE = "low_confidence"
    INJECTION = "injection"
    MASK_FAILED = "mask_failed"
    RUNBOOK_APPROVAL = "runbook_approval"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    EDIT_AND_SEND = "edit_and_send"
    REJECT = "reject"
    REROUTE = "reroute"
    ESCALATE = "escalate"


class Verdict(StrEnum):
    CORRECT = "correct"
    WRONG = "wrong"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"


class UserRole(StrEnum):
    EMPLOYEE = "employee"
    TECHNICIAN = "technician"
    MANAGER = "manager"
    SECURITY = "security"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
