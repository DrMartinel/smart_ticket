"""
Tier-1 regex PII patterns — spec §5.1. Vietnamese + English mixed input
(spec §0), so patterns cover VN-specific formats (phone, CCCD) alongside
generic ones (email, IP, secrets).

Ordering matters: CRITICAL patterns are checked first and short-circuit
the whole pipeline (spec §5.2 — "critical phải bị chặn trước khi bất kỳ
gì được gọi").
"""

from enum import StrEnum

import re


# The PII level masking assigns to a ticket (spec §4.1). Decided here, by
# the patterns below and the NER tier in masking.py; everything downstream
# only reads it.
class PIILevel(StrEnum):
    ROUTINE = "routine"  # name, internal email, employee code → proceeds
    SENSITIVE = "sensitive"  # national ID, bank account, health → proceeds, flagged
    CRITICAL = "critical"  # password / token / API key → BLOCK
    MASK_FAILED = "mask_failed"  # masker errored / uncertain → HITL


# label -> (compiled pattern, PIILevel)
CRITICAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "PASSWORD": re.compile(r"(?i)\b(password|mật\s*khẩu|mat\s*khau|pass)\s*[:=]\s*\S+"),
    "TOKEN": re.compile(
        r"(?i)\b(api[_ -]?key|api[_ -]?token|access[_ -]?token|bearer|secret[_ -]?key|token)\s*[:=]\s*\S+"
    ),
    "AWS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GENERIC_SECRET_ASSIGN": re.compile(r"(?i)\b(secret|otp|mã\s*otp|ma\s*otp)\s*[:=]\s*\S+"),
}

SENSITIVE_PATTERNS: dict[str, re.Pattern[str]] = {
    "CCCD": re.compile(r"\b\d{12}\b"),  # Vietnamese national ID, 12 digits
    # Keyword-anchored, in Vietnamese and English (demo tickets are English):
    # a bare 8-16 digit run is too common (order numbers, ticket ids) to mask.
    "BANK_ACCOUNT": re.compile(
        r"\b(?:STK|so\s*tai\s*khoan|số\s*tài\s*khoản"
        r"|bank\s*account(?:\s*(?:number|no\.?))?|account\s*(?:number|no\.?)|acct\.?(?:\s*no\.?)?)"
        r"\s*[:.]?\s*\d{8,16}\b",
        re.I,
    ),
}

ROUTINE_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "PHONE_VN": re.compile(r"(?:\+84|0)(?:3|5|7|8|9)\d{8}\b"),
    "EMPLOYEE_CODE": re.compile(r"\bNV-?\d{4,7}\b", re.I),
    "INTERNAL_IP": re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3})\b"
    ),
}

LEVEL_BY_GROUP = {
    "critical": PIILevel.CRITICAL,
    "sensitive": PIILevel.SENSITIVE,
    "routine": PIILevel.ROUTINE,
}

ALL_GROUPS = {
    "critical": CRITICAL_PATTERNS,
    "sensitive": SENSITIVE_PATTERNS,
    "routine": ROUTINE_PATTERNS,
}
