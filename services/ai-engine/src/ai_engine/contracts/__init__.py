"""
ai-engine's copy of the core-api ↔ ai-engine wire contract (ADR-0010).

Each service is deployed on its own, so each holds its own copy of the
schemas it needs instead of importing a shared package. core-api's copy
(`services/core-api/contracts`) is the fuller one; this one keeps only what
ai-engine reads or writes. Change a shape in BOTH copies in the same PR —
`evals/suites/test_contract_parity.py` compares the JSON schemas of
`AIRunRequest` and `AIRunResponse` across the two and fails on any drift.

Naming convention: every field authored by the LLM carries a `proposed_`
(or `self_`) prefix. This is a deliberate type-level reminder that the
value is a *suggestion*, not a decision — see ADR-0001 and ADR-0003.
"""

from ai_engine.contracts.enums import PIILevel, TicketCategory
from ai_engine.contracts.ticket import TicketMasked
from ai_engine.contracts.llm_draft import (
    AutoReplyProposal,
    InsufficientContext,
    LLMProposal,
    LLMProposalEnvelope,
    RouteProposal,
    RunbookProposal,
)
from ai_engine.contracts.trust import (
    GenerationSignals,
    PolicySignals,
    RetrievalSignals,
    TrustSignals,
)
from ai_engine.contracts.ai_request import AIRunRequest, AIRunResponse

__all__ = [
    "PIILevel",
    "TicketCategory",
    "TicketMasked",
    "AutoReplyProposal",
    "InsufficientContext",
    "LLMProposal",
    "LLMProposalEnvelope",
    "RouteProposal",
    "RunbookProposal",
    "GenerationSignals",
    "PolicySignals",
    "RetrievalSignals",
    "TrustSignals",
    "AIRunRequest",
    "AIRunResponse",
]
