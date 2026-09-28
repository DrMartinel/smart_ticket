"""
Enums ai-engine reads or writes on the wire — spec §4.1.

ai-engine's own copy (ADR-0010). Only the enums that cross the core-api ↔
ai-engine boundary live here. `Branch`, `ReasonCode`, `ReviewQueue` and the
rest stay in core-api's copy: ai-engine has no routing authority, so it has
no business naming a branch. Values must match core-api's copy exactly —
`evals/suites/test_contract_parity.py` fails if they drift.
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
