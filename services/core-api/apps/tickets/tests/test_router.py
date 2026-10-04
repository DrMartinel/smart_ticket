"""
router.route() branch coverage — spec §8.1's first requirement is that
this function is testable end to end without DB/LLM/network. These tests
hold that promise: no django_db marker needed anywhere in this file.
"""

from typing import Any

from uuid import UUID

from apps.tickets.utils.router import Branch, KBArticleMeta, ReasonCode, ReviewQueue, route
from config.settings.base import (
    AlertThresholds,
    BudgetThresholds,
    ClassificationThresholds,
    FewshotThresholds,
    IncidentThresholds,
    MaskingThresholds,
    RetrievalThresholds,
    RoutingThresholds,
    Thresholds,
)
from apps.tickets.utils.patterns import PIILevel
from infrastructure.dtos import (
    AutoReplyProposal,
    ClassificationSignals,
    GenerationSignals,
    ClarificationProposal,
    InsufficientContext,
    LLMProposalEnvelope,
    PolicySignals,
    RetrievalSignals,
    RouteProposal,
    RunbookProposal,
    TicketCategory,
    TrustSignals,
)


def make_thresholds(**overrides) -> Thresholds:
    base: dict[str, Any] = dict(
        version="test",
        calibration_source="test",
        routing=RoutingThresholds(t_auto=0.88, t_route=0.72, quote_match=0.95),
        retrieval=RetrievalThresholds(
            floor=0.30,
            margin=0.08,
            bm25_top_k=20,
            vector_top_k=20,
            rrf_k=60,
            rerank_top_n=3,
            keyword_agreement_k=3,
        ),
        incident=IncidentThresholds(
            similarity=0.85, window_minutes=15, min_count=5, sigma_multiplier=3.0
        ),
        fewshot=FewshotThresholds(
            max_per_category=5, ttl_days=90, min_diversity=0.3, require_user_confirmed=True
        ),
        budget=BudgetThresholds(
            max_latency_sec=30,
            daily_cost_ceiling_usd=50,
        ),
        alerts=AlertThresholds(
            reviewer_approve_rate_max=0.95,
            reviewer_median_time_min_sec=10,
            override_rate_delta_max=0.05,
            trust_score_drift_max=0.10,
            trust_score_std_min=0.08,
        ),
        classification=ClassificationThresholds(min_confidence=0.65),
        masking=MaskingThresholds(ner_max_share=0.5),
    )
    base.update(overrides)
    return Thresholds(**base)


TH = make_thresholds()


def good_signals(**overrides) -> TrustSignals:
    s = TrustSignals(
        retrieval=RetrievalSignals(
            rerank_top1=0.9,
            rerank_margin=0.3,
            bm25_rank_of_top1=1,
            docs_above_floor=3,
        ),
        generation=GenerationSignals(
            quote_match_ratio=1.0,
            quote_source_in_topk=True,
            quote_applicable=True,
            clarify_options_in_topk=False,
            negation_consistent=True,
        ),
        policy=PolicySignals(
            kb_auto_reply_allowed=True,
            kb_risk_tier="low",
            pii_level=PIILevel.ROUTINE,
            injection_detected=False,
            mass_incident=False,
        ),
        classification=ClassificationSignals(
            category_choice=TicketCategory.NETWORK, category_confidence=0.9
        ),
    )
    for path, value in overrides.items():
        group, field = path.split(".")
        setattr(getattr(s, group), field, value)
    return s


def kb(**overrides) -> KBArticleMeta:
    base: dict[str, Any] = dict(
        id=UUID(int=1),
        slug="identity-center.resetpassword-accessportal",
        category=TicketCategory.ACCESS,
        auto_reply_allowed=True,
        risk_tier="low",
    )
    base.update(overrides)
    return KBArticleMeta(**base)


def auto_reply_proposal(**overrides) -> LLMProposalEnvelope:
    base: dict[str, Any] = dict(
        proposed_intent="auto_reply",
        kb_slug="identity-center.resetpassword-accessportal",
        verbatim_quote="0123456789 verbatim quote text",
        answer_draft="draft",
        self_confidence=90,
    )
    base.update(overrides)
    return LLMProposalEnvelope(root=AutoReplyProposal(**base))


def route_proposal(**overrides) -> LLMProposalEnvelope:
    base: dict[str, Any] = dict(
        proposed_intent="route_to_team",
        rationale="r",
        self_confidence=90,
    )
    base.update(overrides)
    return LLMProposalEnvelope(root=RouteProposal(**base))


def runbook_proposal(**overrides) -> LLMProposalEnvelope:
    base: dict[str, Any] = dict(
        proposed_intent="runbook",
        runbook_id="RB-1",
        draft_payload={"a": 1},
        self_confidence=99,
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
    signals = good_signals(
        **{"policy.mass_incident": True, "policy.pii_level": PIILevel.MASK_FAILED}
    )
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.ESCALATE
    assert d.reason_code is ReasonCode.MASS_INCIDENT


def test_mask_failed_goes_to_mask_failed_queue_priority_1():
    signals = good_signals(**{"policy.pii_level": PIILevel.MASK_FAILED})
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.PII_MASK_FAILED
    assert d.queue is not None
    assert d.queue.value == "mask_failed"
    assert d.priority == 1


def test_no_proposal_is_schema_invalid():
    d = route(good_signals(), None, kb(), TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.SCHEMA_INVALID


def test_insufficient_context_is_retrieval_floor():
    proposal = LLMProposalEnvelope(
        root=InsufficientContext(proposed_intent="insufficient_context", missing_information="x")
    )
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
            "retrieval.bm25_rank_of_top1": None,
            "retrieval.docs_above_floor": 0,
        }
    )
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.reason_code is ReasonCode.TRUST_BELOW_AUTO


def test_auto_reply_all_checks_pass():
    d = route(good_signals(), auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.AUTO_REPLY
    assert d.reason_code is ReasonCode.ALL_CHECKS_PASSED
    assert d.kb_slug == "identity-center.resetpassword-accessportal"
    assert d.trust is not None


# ── Runbook: ALWAYS HITL, no threshold escape hatch (ADR-0006) ─────────


def test_runbook_always_hitl_even_with_perfect_signals():
    d = route(good_signals(), runbook_proposal(), kb(), TH)
    assert d.branch is Branch.HITL
    assert d.queue is not None
    assert d.queue.value == "runbook_approval"
    assert d.draft_payload == {"a": 1}


def test_runbook_hitl_even_with_no_kb_at_all():
    # Runbooks don't need KB authorization — they need human approval,
    # unconditionally, regardless of KB state.
    d = route(good_signals(), runbook_proposal(), None, TH)
    assert d.branch is Branch.HITL
    assert d.queue is not None
    assert d.queue.value == "runbook_approval"


# ── Auto-route branch ────────────────────────────────────────────────────


def test_auto_route_without_a_jev_category_goes_to_a_human():
    """A run where Jev was never asked (refused at the injection guard, or
    degraded) has no category to route on. The LLM's is not a fallback."""
    signals = good_signals()
    signals.classification = ClassificationSignals(category_choice=None, category_confidence=0.0)
    d = route(signals, route_proposal(), None, TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.CATEGORY_LOW_CONFIDENCE


def test_auto_route_below_min_confidence_goes_to_a_human():
    signals = good_signals(**{"classification.category_confidence": 0.64})
    d = route(signals, route_proposal(), None, TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.CATEGORY_LOW_CONFIDENCE


def test_auto_route_at_min_confidence_routes():
    """The threshold is inclusive: `min_confidence` itself is enough."""
    signals = good_signals(**{"classification.category_confidence": 0.65})
    d = route(signals, route_proposal(), None, TH)
    assert d.branch is Branch.AUTO_ROUTE


def test_auto_route_goes_to_jevs_category():
    """ADR-0017: the team a ticket is routed to is Jev's choice; the
    proposal carries no category since propose.v8."""
    signals = good_signals(**{"classification.category_choice": TicketCategory.HARDWARE})
    d = route(signals, route_proposal(), None, TH)
    assert d.branch is Branch.AUTO_ROUTE
    assert d.category is TicketCategory.HARDWARE


def test_auto_reply_needs_no_jev_confidence():
    """An auto-reply takes its KB page's category, not Jev's: an unsure Jev
    must not add human work where the category isn't used."""
    signals = good_signals()
    signals.classification = ClassificationSignals(category_choice=None, category_confidence=0.0)
    d = route(signals, auto_reply_proposal(), kb(), TH)
    assert d.branch is Branch.AUTO_REPLY


def test_auto_route_trust_below_route_threshold():
    # Everything — including the quote-related fields, which RouteProposal
    # never checks — is at its weakest.
    signals = good_signals(
        **{
            "retrieval.rerank_top1": 0.45,
            "retrieval.rerank_margin": 0.0,
            "retrieval.bm25_rank_of_top1": None,
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


def test_refuse_before_llm_reports_retrieval_floor_not_schema_invalid():
    """When the graph refuses before calling the LLM (spec §6.2), there is
    no proposal to validate. The schema gate used to fire first and label
    that SCHEMA_INVALID — blaming malformed model output for what was
    really "the KB had nothing close enough". Same queue either way, so
    only the reason_code changed; but reason_code is what spec §4.1's
    "which reason sent the most tickets to review" is built on, and a
    gate that misreports its cause makes that dashboard quietly wrong."""
    signals = good_signals(**{"retrieval.rerank_top1": 0.10})
    d = route(signals, None, None, TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.RETRIEVAL_FLOOR


def test_genuine_schema_failure_above_floor_still_reports_schema_invalid():
    """The reordering must not swallow real schema failures: retrieval
    cleared the floor, so an absent/invalid proposal is genuinely a
    generation problem."""
    signals = good_signals(**{"retrieval.rerank_top1": 0.90})
    d = route(signals, None, None, TH)
    assert d.reason_code is ReasonCode.SCHEMA_INVALID


def test_unhandled_proposal_type_degrades_to_hitl_rather_than_falling_through():
    """The final fallthrough in route(): a proposal whose root matches none
    of the four known variants.

    Unreachable today — LLMProposal's discriminated union has exactly four
    members and each has its own branch above. It exists for the moment a
    fifth is added to the proposal union and someone forgets to extend this
    function. Without the fallthrough, route() would return None and
    core-api would crash on `.branch`; with it, the ticket degrades to a
    human with SCHEMA_INVALID.

    This is the "degrade toward humans" invariant applied to the router's
    own extensibility, and it is the one line keeping the 100% coverage
    gate in eval-gate.yml honest.
    """

    class _FutureProposal:
        """Stands in for a fifth union member that does not exist yet."""

    class _Envelope:
        root = _FutureProposal()

    d = route(good_signals(), _Envelope(), kb(), TH)  # type: ignore[arg-type]

    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.SCHEMA_INVALID


def test_keyword_agreement_k_comes_from_the_thresholds_passed_in():
    """The router is pure (hard rule 1): `k` must come from the `th` it is
    given, not from settings. Otherwise a replay against
    `routing_decisions.thresholds_used` would silently score with today's `k`.
    Rank 2 agrees under k=3 and not under k=1, so trust must differ."""

    signals = good_signals(**{"retrieval.bm25_rank_of_top1": 2})
    strict = make_thresholds(retrieval=TH.retrieval.model_copy(update={"keyword_agreement_k": 1}))

    loose_trust = route(signals, route_proposal(), None, TH).trust
    strict_trust = route(signals, route_proposal(), None, strict).trust

    assert loose_trust is not None and strict_trust is not None
    assert loose_trust > strict_trust


# --- clarify (ADR-0016) --------------------------------------------------------


def clarify_proposal(**overrides) -> LLMProposalEnvelope:
    base: dict[str, Any] = dict(
        proposed_intent="clarify",
        proposed_question="Which password do you need to reset?",
        proposed_options=[
            "identity-center.resetpassword-accessportal",
            "iam.id_credentials_passwords_admin-change-user",
        ],
        rationale="the ticket names no system",
    )
    base.update(overrides)
    return LLMProposalEnvelope(root=ClarificationProposal(**base))


def test_clarify_on_a_possible_security_incident_goes_to_a_human():
    """A possible incident never waits on a requester's answer, whatever
    else checks out."""
    d = route(
        good_signals(
            **{
                "generation.clarify_options_in_topk": True,
                "classification.category_choice": TicketCategory.SECURITY,
            }
        ),
        clarify_proposal(),
        None,
        TH,
    )
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.CLARIFY_SECURITY


def test_clarify_security_needs_no_confidence():
    """A possible incident goes to a human even when Jev is unsure: the
    security rule comes before the confidence gate."""
    d = route(
        good_signals(
            **{
                "generation.clarify_options_in_topk": True,
                "classification.category_choice": TicketCategory.SECURITY,
                "classification.category_confidence": 0.3,
            }
        ),
        clarify_proposal(),
        None,
        TH,
    )
    assert d.reason_code is ReasonCode.CLARIFY_SECURITY


def test_clarify_on_a_category_jev_is_unsure_of_goes_to_a_human():
    d = route(
        good_signals(
            **{
                "generation.clarify_options_in_topk": True,
                "classification.category_confidence": 0.5,
            }
        ),
        clarify_proposal(),
        None,
        TH,
    )
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.CATEGORY_LOW_CONFIDENCE


def test_clarify_with_options_not_shown_goes_to_a_human():
    """The default of the signal: a question between pages the model never
    saw is not asked. Also covers rows and runs where validation didn't run."""
    d = route(good_signals(), clarify_proposal(), None, TH)
    assert d.branch is Branch.HITL
    assert d.reason_code is ReasonCode.CLARIFY_OPTIONS_NOT_SHOWN


def test_clarify_passes_hard_gates_first():
    """An injection that proposes a question is still blocked."""
    d = route(
        good_signals(
            **{"policy.injection_detected": True, "generation.clarify_options_in_topk": True}
        ),
        clarify_proposal(),
        None,
        TH,
    )
    assert d.branch is Branch.BLOCK


def test_clarify_needs_no_trust_and_lands_in_the_clarification_queue():
    """Low trust doesn't stop a question: asking grants nothing (ADR-0016).
    The decision names the queue a person asks it from."""
    signals = good_signals(
        **{
            "generation.clarify_options_in_topk": True,
            "retrieval.rerank_top1": 0.31,
            "retrieval.rerank_margin": 0.0,
            "retrieval.bm25_rank_of_top1": None,
        }
    )
    d = route(signals, clarify_proposal(), None, TH)
    assert d.branch is Branch.CLARIFY
    assert d.reason_code is ReasonCode.ALL_CHECKS_PASSED
    assert d.queue is ReviewQueue.CLARIFICATION
    # Jev's category (good_signals: network), not the proposal's (access).
    assert d.category is TicketCategory.NETWORK
    assert d.trust is None
