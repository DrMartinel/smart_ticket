"""
router.route() branch coverage — spec §8.1's first requirement is that
this function is testable end to end without DB/LLM/network. These tests
hold that promise: no django_db marker needed anywhere in this file.
"""

import pytest

from contracts.enums import Branch, PIILevel, ReasonCode, TicketCategory
from contracts.llm_draft import (
    AutoReplyProposal,
    InsufficientContext,
    LLMProposalEnvelope,
    RouteProposal,
    RunbookProposal,
)
from contracts.routing import (
    AlertThresholds,
    BudgetThresholds,
    FewshotThresholds,
    IncidentThresholds,
    KBArticleMeta,
    RetrievalThresholds,
    RoutingThresholds,
    Thresholds,
)
from contracts.trust import GenerationSignals, PolicySignals, RetrievalSignals, TrustSignals

from apps.tickets.services.router import route


def make_thresholds(**overrides) -> Thresholds:
    base = dict(
        version="test",
        calibration_source="test",
        routing=RoutingThresholds(t_auto=0.88, t_route=0.72, quote_match=0.95),
        retrieval=RetrievalThresholds(floor=0.45, margin=0.08, bm25_top_k=20, vector_top_k=20, rrf_k=60, rerank_top_n=3),
        incident=IncidentThresholds(similarity=0.85, window_minutes=15, min_count=5, sigma_multiplier=3.0),
        fewshot=FewshotThresholds(max_per_category=5, ttl_days=90, min_diversity=0.3, require_user_confirmed=True),
        budget=BudgetThresholds(
            max_tokens_per_ticket=8000, max_llm_calls=4, max_latency_sec=30, max_graph_iterations=5,
            daily_cost_ceiling_usd=50,
        ),
        alerts=AlertThresholds(
            reviewer_approve_rate_max=0.95, reviewer_median_time_min_sec=10,
            override_rate_delta_max=0.05, trust_score_drift_max=0.10,
        ),
    )
    base.update(overrides)
    return Thresholds(**base)


TH = make_thresholds()


def good_signals(**overrides) -> TrustSignals:
    s = TrustSignals(
        retrieval=RetrievalSignals(rerank_top1=0.9, rerank_margin=0.3, bm25_keyword_hit=True, docs_above_floor=3),
        generation=GenerationSignals(
            schema_valid=True, quote_match_ratio=1.0, quote_source_in_topk=True,
            negation_consistent=True, category_consistent=True,
        ),
        policy=PolicySignals(
            kb_auto_reply_allowed=True, kb_risk_tier="low", pii_level=PIILevel.ROUTINE,
            injection_detected=False, mass_incident=False,
        ),
    )
    for path, value in overrides.items():
        group, field = path.split(".")
        setattr(getattr(s, group), field, value)
    return s


def kb(**overrides) -> KBArticleMeta:
    base = dict(id=1, slug="KB-0001", category=TicketCategory.ACCESS, auto_reply_allowed=True, risk_tier="low")
    base.update(overrides)
    return KBArticleMeta(**base)


def auto_reply_proposal(**overrides) -> LLMProposalEnvelope:
    base = dict(
        proposed_intent="auto_reply", kb_slug="KB-0001",
        verbatim_quote="0123456789 verbatim quote text", answer_draft="draft", self_confidence=90,
    )
    base.update(overrides)
    return LLMProposalEnvelope(root=AutoReplyProposal(**base))


def route_proposal(**overrides) -> LLMProposalEnvelope:
    base = dict(proposed_intent="route_to_team", proposed_category=TicketCategory.NETWORK, rationale="r", self_confidence=90)
    base.update(overrides)
    return LLMProposalEnvelope(root=RouteProposal(**base))


def runbook_proposal(**overrides) -> LLMProposalEnvelope:
    base = dict(
        proposed_intent="runbook", runbook_id="RB-1", draft_payload={"a": 1},
        proposed_category=TicketCategory.SOFTWARE, self_confidence=99,
    )
    base.update(overrides)
    return LLMProposalEnvelope(root=RunbookProposal(**base))


# ── Hard gates ──────────────────────────────────────────────────────────

def test_injection_blocks_and_alerts_security():
    signals = good_signals(**{"policy.injection_detected": True})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.BLOCK
    assert d.reason_code is ReasonCode.INJECTION_DETECTED
    assert d.alert_security is True


def test_pii_critical_blocks_and_alerts_security():
    signals = good_signals(**{"policy.pii_level": PIILevel.CRITICAL})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.BLOCK
    assert d.reason_code is ReasonCode.PII_CRITICAL
    assert d.alert_security is True


def test_mass_incident_escalates_before_mask_failed_check():
    # Both mass_incident AND mask_failed are true — mass_incident must win,
    # because it's checked first (spec §8, ordering is load-bearing).
    signals = good_signals(**{"policy.mass_incident": True, "policy.pii_level": PIILevel.MASK_FAILED})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.ESCALATE
    assert d.reason_code is ReasonCode.MASS_INCIDENT


def test_mask_failed_goes_to_mask_failed_queue_priority_1():
    signals = good_signals(**{"policy.pii_level": PIILevel.MASK_FAILED})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.PII_MASK_FAILED
    assert d.queue.value == "mask_failed"
    assert d.priority == 1


def test_no_proposal_is_schema_invalid():
    d = route(good_signals(), None, kb(), TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.SCHEMA_INVALID


def test_schema_invalid_generation_flag():
    signals = good_signals(**{"generation.schema_valid": False})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.reason_code is ReasonCode.SCHEMA_INVALID


def test_insufficient_context_is_retrieval_floor():
    proposal = LLMProposalEnvelope(root=InsufficientContext(proposed_intent="insufficient_context", missing_information="x"))
    d = route(good_signals(), proposal, kb(), TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.RETRIEVAL_FLOOR


def test_below_retrieval_floor():
    signals = good_signals(**{"retrieval.rerank_top1": 0.1})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.RETRIEVAL_FLOOR


# ── Auto-reply branch ────────────────────────────────────────────────────

def test_auto_reply_requires_kb_present():
    d = route(good_signals(), auto_reply_proposal(), None, TH)
    assert d.reason_code is ReasonCode.KB_NOT_AUTHORIZED


def test_auto_reply_requires_kb_flag_true():
    d = route(good_signals(), auto_reply_proposal(), kb(auto_reply_allowed=False), TH)
    assert d.reason_code is ReasonCode.KB_NOT_AUTHORIZED


def test_auto_reply_quote_source_must_be_in_topk():
    signals = good_signals(**{"generation.quote_source_in_topk": False})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.reason_code is ReasonCode.QUOTE_SOURCE_MISMATCH


def test_auto_reply_quote_match_ratio_below_threshold():
    signals = good_signals(**{"generation.quote_match_ratio": 0.5})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.reason_code is ReasonCode.QUOTE_INVALID


def test_auto_reply_negation_mismatch():
    signals = good_signals(**{"generation.negation_consistent": False})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.reason_code is ReasonCode.NEGATION_MISMATCH


def test_auto_reply_trust_below_auto_threshold():
    # Retrieval barely clears the floor gate and every signal NOT already
    # forced true by an earlier boolean gate (quote_match/quote_source/
    # negation must pass to get this far) is at its weakest — this is the
    # worst case that still reaches the trust check at all.
    signals = good_signals(
        **{
            "retrieval.rerank_top1": 0.45,
            "retrieval.rerank_margin": 0.0,
            "retrieval.bm25_keyword_hit": False,
            "retrieval.docs_above_floor": 0,
            "generation.category_consistent": False,
        }
    )
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.reason_code is ReasonCode.TRUST_BELOW_AUTO


def test_auto_reply_all_checks_pass():
    d = route(good_signals(), auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.AUTO_REPLY
    assert d.reason_code is ReasonCode.ALL_CHECKS_PASSED
    assert d.kb_slug == "KB-0001"
    assert d.trust is not None


# ── Runbook: ALWAYS HITL, no threshold escape hatch (ADR-0006) ─────────

def test_runbook_always_hitl_even_with_perfect_signals():
    d = route(good_signals(), runbook_proposal(), kb(), TH)
    assert d.branch is Branch.HITL
    assert d.queue.value == "runbook_approval"
    assert d.draft_payload == {"a": 1}


def test_runbook_hitl_even_with_no_kb_at_all():
    # Runbooks don't need KB authorization — they need human approval,
    # unconditionally, regardless of KB state.
    d = route(good_signals(), runbook_proposal(), None, TH)
    assert d.branch is Branch.HITL
    assert d.queue.value == "runbook_approval"


# ── Auto-route branch ────────────────────────────────────────────────────

def test_auto_route_category_inconsistent():
    signals = good_signals(**{"generation.category_consistent": False})
    d = route(signals, route_proposal(), None, TH)
    assert d.reason_code is ReasonCode.CATEGORY_INCONSISTENT


def test_auto_route_trust_below_route_threshold():
    # category_consistent must stay True (else CATEGORY_INCONSISTENT fires
    # first); everything else — including the quote-related fields, which
    # RouteProposal never checks — is at its weakest.
    signals = good_signals(
        **{
            "retrieval.rerank_top1": 0.45,
            "retrieval.rerank_margin": 0.0,
            "retrieval.bm25_keyword_hit": False,
            "retrieval.docs_above_floor": 0,
            "generation.quote_match_ratio": 0.0,
            "generation.quote_source_in_topk": False,
            "generation.negation_consistent": False,
        }
    )
    d = route(signals, route_proposal(), None, TH)
    assert d.reason_code is ReasonCode.TRUST_BELOW_ROUTE


def test_auto_route_all_checks_pass():
    d = route(good_signals(), route_proposal(), None, TH)
    assert d.branch is Branch.AUTO_ROUTE
    assert d.reason_code is ReasonCode.ALL_CHECKS_PASSED
    assert d.category == TicketCategory.NETWORK


# ── Router purity ─────────────────────────────────────────────────────

def test_route_is_deterministic_pure_function():
    s, p, k = good_signals(), auto_reply_proposal(), kb()
    d1 = route(s, p, k, TH)
    d2 = route(s, p, k, TH)
    assert d1.branch == d2.branch
    assert d1.reason_code == d2.reason_code
