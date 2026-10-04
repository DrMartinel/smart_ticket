"""
`pipeline.trust_signals`: ai-engine's findings plus the policy core-api owns.
The KB page's authority comes from core-api's own read, never from anything
ai-engine reports (ADR-0002), and no page means auto-reply is denied. Pure,
so no database.
"""

from uuid import UUID

from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.pipeline import trust_signals
from apps.tickets.utils.router import KBArticleMeta, RiskTier
from infrastructure.dtos import (
    ClassificationSignals,
    EngineSignals,
    GenerationSignals,
    RetrievalSignals,
    TicketCategory,
)


def _engine(*, injection: bool = False) -> EngineSignals:
    return EngineSignals(
        retrieval=RetrievalSignals(rerank_top1=0.9, rerank_margin=0.1, docs_above_floor=2),
        generation=GenerationSignals(
            quote_applicable=True,
            quote_match_ratio=1.0,
            quote_source_in_topk=True,
            negation_consistent=True,
            clarify_options_in_topk=False,
        ),
        classification=ClassificationSignals(
            category_choice=TicketCategory.ACCESS, category_confidence=0.9
        ),
        injection_detected=injection,
        llm_self_confidence=80.0,
    )


def _kb(*, allowed: bool, tier: RiskTier) -> KBArticleMeta:
    return KBArticleMeta(
        id=UUID(int=1),
        slug="identity-center.resetpassword-accessportal",
        category=TicketCategory.ACCESS,
        auto_reply_allowed=allowed,
        risk_tier=tier,
    )


# --- failure paths first ------------------------------------------------------


def test_no_kb_page_denies_auto_reply():
    """No active page for the proposal (or no auto-reply proposal at all)
    must never read as authority granted: deny, at the highest risk tier."""

    policy = trust_signals(_engine(), PIILevel.ROUTINE, None).policy

    assert (policy.kb_auto_reply_allowed, policy.kb_risk_tier) == (False, "high")


def test_an_injection_ai_engine_found_reaches_the_policy_gate():
    """The router blocks on `policy.injection_detected`; dropped here, an
    injection would be routed like any ticket."""

    assert trust_signals(_engine(injection=True), PIILevel.ROUTINE, None).policy.injection_detected


# --- behaviour ------------------------------------------------------------------


def test_kb_authority_is_core_apis_own_read():
    policy = trust_signals(_engine(), PIILevel.ROUTINE, _kb(allowed=True, tier=RiskTier.LOW)).policy

    assert (policy.kb_auto_reply_allowed, policy.kb_risk_tier) == (True, "low")


def test_the_pii_level_is_the_tickets_and_mass_incident_is_not_set_here():
    """The PII level comes from core-api's masking; a mass incident never
    reaches ai-engine (the pipeline routes it before), so it is False."""

    policy = trust_signals(_engine(), PIILevel.SENSITIVE, None).policy

    assert policy.pii_level is PIILevel.SENSITIVE
    assert policy.mass_incident is False


def test_ai_engines_findings_pass_through_unchanged():
    engine = _engine()

    signals = trust_signals(engine, PIILevel.ROUTINE, None)

    assert signals.retrieval == engine.retrieval
    assert signals.generation == engine.generation
    assert signals.classification == engine.classification
    assert signals.llm_self_confidence == 80.0
