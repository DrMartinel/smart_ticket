"""
The per-ticket pipeline that runs after submission has masked the ticket:
embed/incident-check → ai-engine → trust score → route →
execute-or-enqueue-HITL. This is the one place all the pieces from §5–§9
come together per ticket. `tasks.process_ticket` is its Celery entry point.

Every failure here ends in a RoutingDecision and a ReviewItem — never an
exception out of the task. A ticket that raises is left at status="new",
invisible to every queue (spec §10.3).

Each run is recorded as an `AiRun` keyed `{ticket_id}:{attempt}`. With
`acks_late=True` (settings), a redelivered message collides on that key in
`_persist_ai_run` and reuses the existing row rather than creating a second
side effect — so a worker dying mid-task cannot send a double auto-reply.
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from infrastructure.dtos import (
    AIRunResponse,
    EngineSignals,
    GenerationSignals,
    LLMProposalEnvelope,
    ClassificationSignals,
    PolicySignals,
    RetrievalSignals,
    TicketCategory,
    TicketMasked,
    TrustSignals,
)
from infrastructure.ai_engine import AIEngineUnavailable, ai_engine
from apps.tickets.utils.router import (
    Branch,
    KBArticleMeta,
    ReasonCode,
    ReviewQueue,
    RiskTier,
    RoutingDecision as Decision,
)
from apps.tickets.utils.patterns import PIILevel

from apps.audit.models import AuditLog
from apps.kb.models import KbArticle
from apps.review.models import ReviewItem
from apps.tickets.models import AiRun, RoutingDecision, Ticket
from apps.tickets.utils import router as router_service
from apps.tickets.utils.trust_scorer import score as compute_trust

logger = logging.getLogger(__name__)

type TaskResult = dict[str, str | bool]


def trust_signals(
    engine: EngineSignals, pii_level: PIILevel, kb: KBArticleMeta | None
) -> TrustSignals:
    """ai-engine's findings plus the policy core-api knows itself: the
    ticket's PII level and the KB page's authority, from core-api's own KB
    read (ADR-0002; `kb` is None unless an auto-reply proposal names an
    active page, and then auto-reply is denied). Pure."""
    return TrustSignals(
        retrieval=engine.retrieval,
        generation=engine.generation,
        classification=engine.classification,
        policy=PolicySignals(
            kb_auto_reply_allowed=kb.auto_reply_allowed if kb else False,
            kb_risk_tier=kb.risk_tier.value if kb else RiskTier.HIGH.value,
            pii_level=pii_level,
            injection_detected=engine.injection_detected,
            mass_incident=False,
        ),
        llm_self_confidence=engine.llm_self_confidence,
    )


def _kb_meta(proposal: LLMProposalEnvelope | None) -> KBArticleMeta | None:
    """The KB page an auto-reply proposal names, if it is active. Authority
    is read here, never taken from anything ai-engine reports (ADR-0002)."""
    if proposal is None or proposal.root.proposed_intent != "auto_reply":
        return None
    kb = KbArticle.objects.filter(slug=proposal.root.kb_slug, is_active=True).first()
    if kb is None:
        return None
    return KBArticleMeta(
        id=kb.id,
        slug=kb.slug,
        category=TicketCategory(kb.category),
        auto_reply_allowed=kb.auto_reply_allowed,
        risk_tier=RiskTier(kb.risk_tier),
    )


def _degraded_signals() -> TrustSignals:
    return TrustSignals(
        # No rank: a degraded run has no retrieval, so no keyword agreement.
        retrieval=RetrievalSignals(rerank_top1=0.0, rerank_margin=0.0, docs_above_floor=0),
        generation=GenerationSignals(
            quote_match_ratio=0.0,
            quote_source_in_topk=False,
            negation_consistent=False,
        ),
        policy=PolicySignals(
            kb_auto_reply_allowed=False,
            kb_risk_tier="high",
            pii_level=PIILevel.ROUTINE,
            injection_detected=False,
            mass_incident=False,
        ),
        # A degraded run never asked Jev: no category.
        classification=ClassificationSignals(category_choice=None, category_confidence=0.0),
    )


def _degraded_decision(
    reason_code: ReasonCode, queue: ReviewQueue, *, priority: int = 3
) -> Decision:
    return Decision(
        branch=Branch.HITL,
        reason_code=reason_code,
        reason_detail=f"degraded: {reason_code.value}",
        gate_failed=reason_code.value,
        queue=queue,
        priority=priority,
    )


def _persist_ai_run(
    ticket: Ticket,
    idempotency_key: str,
    signals: TrustSignals,
    proposal: LLMProposalEnvelope | None,
    *,
    resp: AIRunResponse | None = None,
    degraded_reason: str | None = None,
) -> AiRun:
    trust = (
        compute_trust(signals, settings.THRESHOLDS.retrieval.keyword_agreement_k)
        if proposal is not None
        else None
    )
    try:
        with transaction.atomic():
            return AiRun.objects.create(
                ticket=ticket,
                idempotency_key=idempotency_key,
                prompt_version=resp.prompt_version if resp else "n/a",
                model=resp.model if resp else "n/a",
                graph_version=resp.graph_version if resp else "n/a",
                proposed_draft=proposal.model_dump(mode="json") if proposal else None,
                llm_self_confidence=signals.llm_self_confidence,
                trust_signals=signals.model_dump(mode="json"),
                trust_score=trust.value if trust else None,
                retrieved_chunks=resp.retrieved_chunks if resp else [],
                tokens_in=resp.tokens_in if resp else None,
                tokens_out=resp.tokens_out if resp else None,
                cost_usd=resp.cost_usd if resp else 0,
                latency_ms=resp.latency_ms if resp else None,
                degraded_reason=degraded_reason,
            )
    except IntegrityError:
        # Idempotency key collision: this exact attempt was already
        # recorded by another delivery of the same message (spec §10.3,
        # acks_late redelivery). Return the existing row instead of
        # creating a duplicate side effect.
        return AiRun.objects.get(idempotency_key=idempotency_key)


def _finalize(
    ticket: Ticket,
    ai_run: AiRun,
    decision: Decision,
    trace_id: str,
    *,
    kb: KBArticleMeta | None = None,
) -> TaskResult:
    shadow = settings.SHADOW_MODE

    with transaction.atomic():
        RoutingDecision.objects.create(
            ticket=ticket,
            ai_run=ai_run,
            branch=decision.branch.value,
            reason_code=decision.reason_code.value,
            reason_detail=decision.reason_detail,
            gate_failed=decision.gate_failed,
            thresholds_used=settings.THRESHOLDS.model_dump(mode="json"),
            shadow_mode=shadow,
        )

        AuditLog.objects.record(
            "routing_decided",
            actor_type="system",
            ticket_id=ticket.id,
            payload={
                "ticket_public_id": ticket.public_id,
                "branch": decision.branch.value,
                "reason_code": decision.reason_code.value,
                "shadow_mode": shadow,
                "thresholds_version": settings.THRESHOLDS.version,
            },
            trace_id=trace_id,
        )

        if decision.alert_security:
            AuditLog.objects.record(
                "security_alert",
                actor_type="system",
                ticket_id=ticket.id,
                payload={"reason_code": decision.reason_code.value},
                trace_id=trace_id,
            )

        _execute_or_enqueue(ticket, ai_run, decision, shadow, kb)

    return {
        "ticket_public_id": ticket.public_id,
        "branch": decision.branch.value,
        "shadow_mode": shadow,
    }


def _execute_or_enqueue(
    ticket: Ticket, ai_run: AiRun, decision: Decision, shadow: bool, kb: KBArticleMeta | None
) -> None:
    branch = decision.branch

    if branch is Branch.BLOCK:
        ticket.status = "blocked"
        ticket.save(update_fields=["status"])
        queue = (
            ReviewQueue.INJECTION
            if decision.reason_code is ReasonCode.INJECTION_DETECTED
            else ReviewQueue.PII_VERIFY
        )
        ReviewItem.objects.create(ticket=ticket, ai_run=ai_run, queue=queue.value, priority=1)
        return

    if branch is Branch.ESCALATE:
        ticket.status = "escalated"
        ticket.save(update_fields=["status"])
        ReviewItem.objects.create(
            ticket=ticket, ai_run=ai_run, queue=ReviewQueue.LOW_CONFIDENCE.value, priority=1
        )
        return

    if branch is Branch.HITL:
        ticket.status = "pending_review"
        ticket.save(update_fields=["status"])
        ReviewItem.objects.create(
            ticket=ticket,
            ai_run=ai_run,
            queue=(decision.queue.value if decision.queue else ReviewQueue.LOW_CONFIDENCE.value),
            priority=decision.priority,
        )
        return

    if branch is Branch.CLARIFY:
        # In shadow mode and out of it: nothing sends a question to the
        # requester yet (ADR-0016, "Not decided"). A person sees the proposed
        # question in the clarification queue and asks it, edits it or
        # ignores it, which is also the data that will judge the branch.
        ticket.status = "pending_review"
        ticket.save(update_fields=["status"])
        ReviewItem.objects.create(
            ticket=ticket,
            ai_run=ai_run,
            queue=ReviewQueue.CLARIFICATION.value,
            priority=decision.priority,
        )
        return

    # branch is AUTO_REPLY or AUTO_ROUTE
    if shadow:
        # Same route() call as live mode (spec §8.2) — only the execution
        # differs. Still surfaced to a human so shadow-mode data reflects
        # exactly what would have happened live.
        ticket.status = "pending_review"
        ticket.save(update_fields=["status"])
        ReviewItem.objects.create(
            ticket=ticket, ai_run=ai_run, queue=ReviewQueue.LOW_CONFIDENCE.value, priority=3
        )
        return

    if branch is Branch.AUTO_REPLY:
        ticket.status = "auto_replied"
        ticket.category = kb.category if kb else ticket.category
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "category", "resolved_at"])
    elif branch is Branch.AUTO_ROUTE:
        ticket.status = "auto_routed"
        ticket.category = decision.category.value if decision.category else ticket.category
        ticket.assigned_team = ticket.category
        ticket.save(update_fields=["status", "category", "assigned_team"])


def ticket_process(ticket_id: str) -> TaskResult:
    """Runs one ticket from embedding to a recorded routing decision.

    Each call is a new attempt: it creates a new `AiRun` and `RoutingDecision`.
    Does not raise for an embedding, ai-engine, LLM or budget failure; those
    reach a human with their own `ReasonCode`.
    """
    ticket = Ticket.objects.select_related("reporter").get(id=ticket_id)
    trace_id = f"ticket-{ticket.public_id}"

    attempt = AiRun.objects.filter(ticket=ticket).count() + 1
    idempotency_key = f"{ticket.id}:{attempt}"

    # ── Embedding + incident detection (core-api owns this, spec §1 map) ──
    combined_text = f"{ticket.subject_masked}\n{ticket.body_masked}"
    try:
        embedding = ai_engine.embed(combined_text)
        ticket.store_embedding(embedding.vector, embedding.model)
        verdict = ticket.classify_similarity(embedding.vector)
    except (httpx.HTTPError, ValueError) as e:
        # Same fail-open-to-human principle as the AIEngineUnavailable
        # branch below (spec §10.3: "khi degrade, luôn đẩy về con người").
        # Without this, an embedding outage left the ticket stuck
        # at status="new" forever — no RoutingDecision, no ReviewItem,
        # invisible to every queue and dashboard.
        logger.warning(
            "embedding unavailable for ticket %s: %s — failing open to HITL", ticket.public_id, e
        )
        signals = _degraded_signals()
        decision = _degraded_decision(
            ReasonCode.EMBEDDING_UNAVAILABLE, ReviewQueue.LOW_CONFIDENCE, priority=2
        )
        ai_run = _persist_ai_run(
            ticket, idempotency_key, signals, None, degraded_reason="embedding_unavailable"
        )
        return _finalize(ticket, ai_run, decision, trace_id)

    if verdict.kind == "duplicate" and verdict.of:
        original = Ticket.objects.filter(id=verdict.of).first()
        if original:
            ticket.duplicate_of = original
            ticket.assigned_team = original.assigned_team
            ticket.assigned_to = original.assigned_to
            ticket.category = ticket.category or original.category
            ticket.save(update_fields=["duplicate_of", "assigned_team", "assigned_to", "category"])

    if verdict.kind == "mass_incident":
        # Skip the AI engine entirely — cost saved, and per spec §9 a mass
        # incident must never receive an (possibly wrong) auto-reply.
        signals = _degraded_signals()
        signals.policy.mass_incident = True
        decision = router_service.route(signals, None, None, settings.THRESHOLDS)
        ai_run = _persist_ai_run(
            ticket, idempotency_key, signals, None, degraded_reason="mass_incident_short_circuit"
        )
        return _finalize(ticket, ai_run, decision, trace_id)

    # ── Budget: daily cost ceiling (core-api owns this — it's the only
    # side with write access to ai_runs, so it's the only side that can
    # actually see total daily spend) ──
    ceiling = settings.THRESHOLDS.budget.daily_cost_ceiling_usd
    if AiRun.objects.cost_today_usd() >= ceiling:
        signals = _degraded_signals()
        decision = _degraded_decision(
            ReasonCode.BUDGET_EXCEEDED, ReviewQueue.LOW_CONFIDENCE, priority=2
        )
        ai_run = _persist_ai_run(
            ticket, idempotency_key, signals, None, degraded_reason="budget_exceeded"
        )
        return _finalize(ticket, ai_run, decision, trace_id)

    # ── Call ai-engine ──
    masked = TicketMasked(
        ticket_public_id=ticket.public_id,
        subject_masked=ticket.subject_masked,
        body_masked=ticket.body_masked,
        pii_level=PIILevel(ticket.pii_level),
        placeholder_keys=list(ticket.pii_map.keys()),
    )

    try:
        resp = ai_engine.analyze(masked, request_id=idempotency_key)
    except AIEngineUnavailable as e:
        logger.warning(
            "ai-engine unavailable for ticket %s: %s — failing open to HITL", ticket.public_id, e
        )
        signals = _degraded_signals()
        decision = _degraded_decision(
            ReasonCode.AI_ENGINE_UNAVAILABLE, ReviewQueue.LOW_CONFIDENCE, priority=2
        )
        ai_run = _persist_ai_run(
            ticket, idempotency_key, signals, None, degraded_reason="ai_engine_unavailable"
        )
        return _finalize(ticket, ai_run, decision, trace_id)

    # The chat LLM failed. Routed here rather than through the router, which
    # sees only proposal=None and would label an outage SCHEMA_INVALID — the
    # same code as "the model returned bad JSON".
    if resp.degraded_reason == ReasonCode.ALL_LLM_DOWN.value:
        decision = _degraded_decision(
            ReasonCode.ALL_LLM_DOWN, ReviewQueue.LOW_CONFIDENCE, priority=2
        )
        ai_run = _persist_ai_run(
            ticket,
            idempotency_key,
            trust_signals(resp.signals, masked.pii_level, None),
            resp.proposal,
            resp=resp,
            degraded_reason=resp.degraded_reason,
        )
        return _finalize(ticket, ai_run, decision, trace_id)

    kb_meta = _kb_meta(resp.proposal)
    signals = trust_signals(resp.signals, masked.pii_level, kb_meta)
    decision = router_service.route(signals, resp.proposal, kb_meta, settings.THRESHOLDS)
    ai_run = _persist_ai_run(
        ticket,
        idempotency_key,
        signals,
        resp.proposal,
        resp=resp,
        degraded_reason=resp.degraded_reason,
    )
    return _finalize(ticket, ai_run, decision, trace_id, kb=kb_meta)
