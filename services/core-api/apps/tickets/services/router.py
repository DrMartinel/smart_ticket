"""
Switch Router — spec §8. The only module allowed to decide `Branch`
(ADR-0001). Pure function: no I/O, no side effects, no imported globals —
`thresholds` and `kb` are always parameters, which is what makes 100%
branch coverage possible with plain unit tests.

Hard gates run in a specific order (spec §8, table §8.1) and that order is
load-bearing: mass_incident is checked BEFORE anything duplicate-related,
because 40 identical tickets in 10 minutes is an outage, not spam to
dedupe. Runbook proposals always resolve to HITL with no trust threshold
that can skip it (ADR-0006).
"""

from __future__ import annotations

from contracts.enums import Branch, PIILevel, ReasonCode, ReviewQueue
from contracts.llm_draft import (
    AutoReplyProposal,
    InsufficientContext,
    LLMProposalEnvelope,
    RouteProposal,
    RunbookProposal,
)
from contracts.routing import KBArticleMeta, RoutingDecision, Thresholds
from contracts.trust import TrustSignals

from apps.tickets.services.trust_scorer import score as compute_trust


def _block(reason_code: ReasonCode, *, detail: str = "", alert_security: bool = False) -> RoutingDecision:
    return RoutingDecision(
        branch=Branch.BLOCK,
        reason_code=reason_code,
        reason_detail=detail or reason_code.value,
        gate_failed=reason_code.value,
        alert_security=alert_security,
    )


def _escalate(reason_code: ReasonCode, *, detail: str = "") -> RoutingDecision:
    return RoutingDecision(
        branch=Branch.ESCALATE,
        reason_code=reason_code,
        reason_detail=detail or reason_code.value,
        gate_failed=reason_code.value,
    )


def _hitl(
    reason_code: ReasonCode,
    *,
    queue: str,
    detail: str = "",
    priority: int = 3,
    draft_payload: dict | None = None,
    gate_failed: str | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        branch=Branch.HITL,
        reason_code=reason_code,
        reason_detail=detail or reason_code.value,
        gate_failed=gate_failed,
        queue=ReviewQueue(queue),
        priority=priority,
        draft_payload=draft_payload,
    )


def route(
    signals: TrustSignals,
    proposal: LLMProposalEnvelope | None,
    kb: KBArticleMeta | None,
    th: Thresholds,
) -> RoutingDecision:
    """Pure function. No I/O, no side effects. Every branch is testable
    without a database, an LLM, or a network call."""

    # ═══════════════ HARD GATES — order has meaning ═══════════════
    p = signals.policy

    if p.injection_detected:
        return _block(ReasonCode.INJECTION_DETECTED, alert_security=True)

    if p.pii_level is PIILevel.CRITICAL:
        return _block(ReasonCode.PII_CRITICAL, alert_security=True)

    if p.mass_incident:
        # BEFORE any duplicate logic. 40 identical tickets in 10 minutes
        # is not something to dedupe quietly — it's an outage to escalate.
        return _escalate(ReasonCode.MASS_INCIDENT)

    if p.pii_level is PIILevel.MASK_FAILED:
        return _hitl(ReasonCode.PII_MASK_FAILED, queue=ReviewQueue.MASK_FAILED.value, priority=1)

    # Retrieval floor is checked BEFORE the schema gate, because when the
    # graph refuses before ever calling the LLM (spec §6.2's
    # refuse-before-LLM edge) there is no proposal to validate — so the
    # schema gate would fire first and label the ticket SCHEMA_INVALID for
    # what was really "the KB had nothing close enough". Both land in the
    # same HITL queue, so this changes no behavior; what it fixes is the
    # reason_code, and reason_code is the entire basis for "which reason
    # sent the most tickets to review this week" (spec §4.1). A gate that
    # reports the wrong cause is worse than no gate, because the dashboard
    # built on it quietly lies.
    if signals.retrieval.rerank_top1 < th.retrieval_floor:
        return _hitl(ReasonCode.RETRIEVAL_FLOOR, queue=ReviewQueue.LOW_CONFIDENCE.value)

    if proposal is None or not signals.generation.schema_valid:
        return _hitl(ReasonCode.SCHEMA_INVALID, queue=ReviewQueue.LOW_CONFIDENCE.value)

    if isinstance(proposal.root, InsufficientContext):
        return _hitl(ReasonCode.RETRIEVAL_FLOOR, queue=ReviewQueue.LOW_CONFIDENCE.value)

    # ═══════════════ TRUST-BASED ROUTING ═══════════════
    trust = compute_trust(signals).value
    g = signals.generation

    # ── Branch A: auto-reply ──
    if isinstance(proposal.root, AutoReplyProposal):
        # Authority comes from KB METADATA, not from the LLM. The model
        # cannot grant itself permission to auto-reply (ADR-0002).
        if kb is None or not kb.auto_reply_allowed:
            return _hitl(ReasonCode.KB_NOT_AUTHORIZED, queue=ReviewQueue.LOW_CONFIDENCE.value)

        if not g.quote_source_in_topk:
            return _hitl(ReasonCode.QUOTE_SOURCE_MISMATCH, queue=ReviewQueue.LOW_CONFIDENCE.value)
        if g.quote_match_ratio < th.quote_match:
            return _hitl(ReasonCode.QUOTE_INVALID, queue=ReviewQueue.LOW_CONFIDENCE.value)
        if not g.negation_consistent:
            return _hitl(ReasonCode.NEGATION_MISMATCH, queue=ReviewQueue.LOW_CONFIDENCE.value)
        if trust < th.t_auto:
            return _hitl(ReasonCode.TRUST_BELOW_AUTO, queue=ReviewQueue.LOW_CONFIDENCE.value)

        return RoutingDecision(
            branch=Branch.AUTO_REPLY,
            reason_code=ReasonCode.ALL_CHECKS_PASSED,
            reason_detail="all auto-reply checks passed",
            kb_slug=kb.slug,
            trust=trust,
        )

    # ── Runbook: ALWAYS through HITL, no exceptions (ADR-0006) ──
    if isinstance(proposal.root, RunbookProposal):
        # No trust comparison in this branch, ever. This is a write to a
        # real system; no threshold is high enough to skip a human here.
        return _hitl(
            ReasonCode.ALL_CHECKS_PASSED,
            queue=ReviewQueue.RUNBOOK_APPROVAL.value,
            detail="runbook proposals always require human approval",
            draft_payload=proposal.root.draft_payload,
        )

    # ── Branch B: auto-route ──
    if isinstance(proposal.root, RouteProposal):
        if not g.category_consistent:
            return _hitl(ReasonCode.CATEGORY_INCONSISTENT, queue=ReviewQueue.LOW_CONFIDENCE.value)
        if trust < th.t_route:
            return _hitl(ReasonCode.TRUST_BELOW_ROUTE, queue=ReviewQueue.LOW_CONFIDENCE.value)

        return RoutingDecision(
            branch=Branch.AUTO_ROUTE,
            reason_code=ReasonCode.ALL_CHECKS_PASSED,
            reason_detail="all auto-route checks passed",
            category=proposal.root.proposed_category,
            trust=trust,
        )

    return _hitl(ReasonCode.SCHEMA_INVALID, queue=ReviewQueue.LOW_CONFIDENCE.value)
