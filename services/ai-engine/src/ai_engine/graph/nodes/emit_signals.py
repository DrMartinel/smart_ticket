"""
Terminal node — spec §6.2 `emit_signals`. Assembles the `TrustSignals` that
core-api's trust scorer and router act on; every path ends here. It NEVER
writes to a database, only reads best-effort for the log-only `policy` fields.
"""

from __future__ import annotations

from contracts.enums import PIILevel
from contracts.trust import GenerationSignals, PolicySignals, RetrievalSignals, TrustSignals

from sqlalchemy import select

from ai_engine.core.db.tables import KbArticle
from ai_engine.core.node import BaseNode
from ai_engine.core.db.client import SqlAlchemySessionSource
from ai_engine.core.state import TriageState, ValidationResult

# Deny-by-default when the policy lookup can't answer. NOT a constructor
# parameter and NOT a Settings field: "degrade toward humans" means there
# must be no configuration in this system that turns a KB-policy lookup
# failure into "auto-reply is allowed". A safety invariant wearing a
# magic-number costume.
_POLICY_FALLBACK_DENY: tuple[bool, str] = (False, "high")


class EmitSignalsNode(BaseNode):
    def __init__(self, *, db: SqlAlchemySessionSource) -> None:
        self._db = db

    def _lookup_kb_policy(self, kb_slug: str | None) -> tuple[bool, str]:
        """Best-effort and log-only — NOT the authority check, which
        core-api's router does against its own KB fetch (ADR-0002).
        Only makes `TrustSignals.policy` informative for audit and UI.
        """

        if not kb_slug:
            return _POLICY_FALLBACK_DENY
        try:
            # `connect()` MUST stay inside the try: a DB outage here has to
            # produce deny-by-default, not a 500 out of the terminal node
            # that every path through the graph passes through.
            statement = select(KbArticle.auto_reply_allowed, KbArticle.risk_tier).where(
                KbArticle.slug == kb_slug, KbArticle.is_active.is_(True)
            )
            with self._db.connect() as session:
                row = session.execute(statement).first()
                if row:
                    return bool(row[0]), row[1]
        except Exception:  # noqa: BLE001 — best-effort only, never fail the graph over this
            pass
        return _POLICY_FALLBACK_DENY

    def __call__(self, state: TriageState) -> dict:
        reranked = state.reranked
        validation = state.validation or ValidationResult.all_failed()
        proposal = state.proposal

        rerank_top1 = reranked[0].score if reranked else 0.0
        rerank_top2 = reranked[1].score if len(reranked) > 1 else 0.0
        rerank_margin = max(0.0, rerank_top1 - rerank_top2) if len(reranked) > 1 else 0.0
        # `retrieval_floor` is read from STATE, never from a constructor
        # param: it arrives per-request in AIRunRequest so core-api stays the
        # single owner of calibration (see core/config.py's module docstring).
        docs_above_floor = sum(1 for r in reranked if r.score >= state.retrieval_floor)

        kb_slug = None
        self_confidence = None
        if proposal is not None and getattr(proposal.root, "proposed_intent", None) == "auto_reply":
            kb_slug = proposal.root.kb_slug
            self_confidence = proposal.root.self_confidence
        elif proposal is not None and hasattr(proposal.root, "self_confidence"):
            self_confidence = proposal.root.self_confidence

        kb_auto_reply_allowed, kb_risk_tier = self._lookup_kb_policy(kb_slug)

        signals = TrustSignals(
            retrieval=RetrievalSignals(
                rerank_top1=rerank_top1,
                rerank_margin=rerank_margin,
                bm25_keyword_hit=state.bm25_keyword_hit,
                docs_above_floor=docs_above_floor,
                topk_chunk_ids=[r.chunk_id for r in reranked],
            ),
            generation=GenerationSignals(
                schema_valid=validation.schema_valid,
                quote_match_ratio=validation.quote_match_ratio,
                quote_source_in_topk=validation.quote_source_in_topk,
                negation_consistent=validation.negation_consistent,
                category_consistent=validation.category_consistent,
                # Computed by the validate node; forwarded so core-api can
                # tell "no quote to check" apart from "the quote failed".
                quote_applicable=validation.quote_applicable,
            ),
            policy=PolicySignals(
                kb_auto_reply_allowed=kb_auto_reply_allowed,
                kb_risk_tier=kb_risk_tier,
                pii_level=state.ticket.pii_level or PIILevel.ROUTINE,
                injection_detected=state.injection is not None and state.injection.detected,
                mass_incident=False,  # not this graph's concern — core-api's incident detector owns it
            ),
            llm_self_confidence=self_confidence,
        )
        return {"signals": signals}
