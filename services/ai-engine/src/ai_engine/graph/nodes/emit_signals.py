"""
Terminal node — spec §6.2 `emit_signals`. Assembles the `TrustSignals`
that everything else (core-api's trust_scorer, router) actually acts on.
This node NEVER writes to any database, business or otherwise — it only
reads (best-effort, for the `policy` block's log-only fields) and returns
a value. Every path through the graph ends here.
"""

from __future__ import annotations

from contracts.enums import PIILevel
from contracts.trust import GenerationSignals, PolicySignals, RetrievalSignals, TrustSignals

from ai_engine.db import get_connection
from ai_engine.graph.state import TriageState


def _lookup_kb_policy(kb_slug: str | None) -> tuple[bool, str]:
    """Best-effort, log-only lookup — NOT the authority check. The
    authoritative auto_reply_allowed check happens in core-api's router
    against its own KBArticleMeta fetch (ADR-0002); this is purely so
    TrustSignals.policy carries something informative for the audit
    trail/UI rather than a placeholder."""

    if not kb_slug:
        return False, "high"
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT auto_reply_allowed, risk_tier FROM kb_articles WHERE slug = %s AND is_active = true",
                (kb_slug,),
            )
            row = cur.fetchone()
            if row:
                return bool(row[0]), row[1]
    except Exception:  # noqa: BLE001 — best-effort only, never fail the graph over this
        pass
    return False, "high"


def build_trust_signals(state: TriageState) -> dict:
    reranked = state.get("reranked", [])
    validation = state.get("validation", {})
    proposal = state.get("proposal")
    injection = state.get("injection", {"detected": False, "matched_patterns": []})

    rerank_top1 = reranked[0].score if reranked else 0.0
    rerank_top2 = reranked[1].score if len(reranked) > 1 else 0.0
    rerank_margin = max(0.0, rerank_top1 - rerank_top2) if len(reranked) > 1 else 0.0
    docs_above_floor = sum(1 for r in reranked if r.score >= state["retrieval_floor"])

    kb_slug = None
    self_confidence = None
    if proposal is not None and getattr(proposal.root, "proposed_intent", None) == "auto_reply":
        kb_slug = proposal.root.kb_slug
        self_confidence = proposal.root.self_confidence
    elif proposal is not None and hasattr(proposal.root, "self_confidence"):
        self_confidence = proposal.root.self_confidence

    kb_auto_reply_allowed, kb_risk_tier = _lookup_kb_policy(kb_slug)

    signals = TrustSignals(
        retrieval=RetrievalSignals(
            rerank_top1=rerank_top1,
            rerank_margin=rerank_margin,
            bm25_keyword_hit=state.get("bm25_keyword_hit", False),
            docs_above_floor=docs_above_floor,
            topk_chunk_ids=[r.chunk_id for r in reranked],
        ),
        generation=GenerationSignals(
            schema_valid=validation.get("schema_valid", False),
            quote_match_ratio=validation.get("quote_match_ratio", 0.0),
            quote_source_in_topk=validation.get("quote_source_in_topk", False),
            negation_consistent=validation.get("negation_consistent", False),
            category_consistent=validation.get("category_consistent", False),
        ),
        policy=PolicySignals(
            kb_auto_reply_allowed=kb_auto_reply_allowed,
            kb_risk_tier=kb_risk_tier,
            pii_level=state["ticket"].pii_level or PIILevel.ROUTINE,
            injection_detected=injection["detected"],
            mass_incident=False,  # not this graph's concern — core-api's incident detector owns it
        ),
        llm_self_confidence=self_confidence,
    )
    return {"signals": signals}
