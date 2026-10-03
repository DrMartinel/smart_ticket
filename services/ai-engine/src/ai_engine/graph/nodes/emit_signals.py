"""
Terminal node — spec §6.2 `emit_signals`. Assembles the `TrustSignals` that
core-api's trust scorer and router act on; every path ends here. It NEVER
writes to a database, only reads best-effort for the log-only `policy` fields.
"""

from __future__ import annotations

import uuid

from ai_engine.schemas import (
    AutoReplyProposal,
    GenerationSignals,
    PIILevel,
    PolicySignals,
    RetrievalSignals,
    TrustSignals,
)
from ai_engine.graph.state import TriageState

from sqlalchemy import select

from ai_engine.core.db.tables import KbArticle
from ai_engine.graph.build.node import BaseNode, StateUpdate
from ai_engine.core.db.client import db

# Deny-by-default when the policy lookup can't answer. NOT a constructor
# parameter and NOT a Settings field: "degrade toward humans" means there
# must be no configuration in this system that turns a KB-policy lookup
# failure into "auto-reply is allowed". A safety invariant wearing a
# magic-number costume.
_POLICY_FALLBACK_DENY: tuple[bool, str] = (False, "high")


def _bm25_rank(bm25_article_ids: list[uuid.UUID], article_id: uuid.UUID) -> int | None:
    """1-based position of `article_id` in BM25's article ranking, or None
    if BM25 didn't return it. core-api turns this into the agreement feature;
    the comparison with `k` is its decision, not this node's."""

    try:
        return bm25_article_ids.index(article_id) + 1
    except ValueError:
        return None


class EmitSignalsNode(BaseNode):
    def _lookup_kb_policy(self, kb_slug: str | None) -> tuple[bool, str]:
        """Best-effort and log-only — NOT the authority check, which
        core-api's router does against its own KB fetch (ADR-0002).
        Only makes `TrustSignals.policy` informative for audit and UI.
        """

        if not kb_slug:
            return _POLICY_FALLBACK_DENY
        try:
            # The read MUST stay inside the try: a DB outage here has to
            # produce deny-by-default, not a 500 out of the terminal node
            # that every path through the graph passes through.
            statement = select(KbArticle.auto_reply_allowed, KbArticle.risk_tier).where(
                KbArticle.slug == kb_slug, KbArticle.is_active.is_(True)
            )
            row = db.first(statement)
            if row:
                return bool(row[0]), row[1]
        except Exception:  # noqa: BLE001 — best-effort only, never fail the graph over this
            pass
        return _POLICY_FALLBACK_DENY

    def __call__(self, state: TriageState) -> StateUpdate:
        reranked = state.reranked
        proposal = state.proposal

        # Jev's scale throughout: the one the floor is set for (ADR-0015).
        # Empty when rerank never ran (injection, no candidates).
        final = [r.final_score() for r in reranked]
        rerank_top1 = final[0] if final else 0.0
        rerank_top2 = final[1] if len(final) > 1 else 0.0
        rerank_margin = max(0.0, rerank_top1 - rerank_top2) if len(reranked) > 1 else 0.0
        # The floor is read from STATE: it arrives per-request in AIRunRequest
        # so core-api stays the single owner of calibration.
        docs_above_floor = sum(1 for s in final if s >= state.retrieval_floor)
        bm25_rank_of_top1 = (
            _bm25_rank(state.bm25_article_ids, reranked[0].article_id) if reranked else None
        )

        root = proposal.root if proposal is not None else None
        # Only an auto-reply cites a KB article whose policy can apply.
        kb_slug = root.kb_slug if isinstance(root, AutoReplyProposal) else None
        # InsufficientContext carries no self_confidence.
        self_confidence = getattr(root, "self_confidence", None)

        kb_auto_reply_allowed, kb_risk_tier = self._lookup_kb_policy(kb_slug)

        signals = TrustSignals(
            retrieval=RetrievalSignals(
                rerank_top1=rerank_top1,
                rerank_margin=rerank_margin,
                bm25_rank_of_top1=bm25_rank_of_top1,
                docs_above_floor=docs_above_floor,
            ),
            generation=GenerationSignals(
                schema_valid=state.schema_valid,
                quote_match_ratio=state.quote_match_ratio,
                quote_source_in_topk=state.quote_source_in_topk,
                negation_consistent=state.negation_consistent,
                category_consistent=state.category_consistent,
                # Computed by the validate node; forwarded so core-api can
                # tell "no quote to check" apart from "the quote failed".
                quote_applicable=state.quote_applicable,
            ),
            policy=PolicySignals(
                kb_auto_reply_allowed=kb_auto_reply_allowed,
                kb_risk_tier=kb_risk_tier,
                pii_level=state.ticket.pii_level or PIILevel.ROUTINE,
                injection_detected=state.injection_detected,
                mass_incident=False,  # not this graph's concern — core-api's incident detector owns it
            ),
            llm_self_confidence=self_confidence,
        )
        return {"signals": signals}


emit_signals = EmitSignalsNode()
