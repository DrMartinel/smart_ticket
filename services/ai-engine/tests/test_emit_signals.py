"""
Terminal-node tests. Every path through the graph ends here, so this node
failing is not a degraded answer — it is no answer at all.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from ai_engine.schemas import AutoReplyProposal, LLMProposalEnvelope, PIILevel, RetrievalSignals
from ai_engine.graph.state import RankedChunk

from ai_engine.graph.nodes.emit_signals import emit_signals


def _auto_reply(kb_slug: str = "kb-a") -> LLMProposalEnvelope:
    """An auto_reply proposal is the ONLY thing that produces a kb_slug, and
    therefore the only state in which the policy lookup runs at all."""

    return LLMProposalEnvelope(
        root=AutoReplyProposal(
            proposed_intent="auto_reply",
            kb_slug=kb_slug,
            verbatim_quote="một đoạn trích đủ dài để hợp lệ",
            answer_draft="draft",
            self_confidence=80.0,
        )
    )


def _chunk(chunk_id: int, score: float, slug: str = "kb-a") -> RankedChunk:
    return RankedChunk(
        chunk_id=UUID(int=chunk_id),
        article_id=UUID(int=chunk_id * 10),
        article_slug=slug,
        content="nội dung",
        shortlist_score=score,
        rerank_score=score,
    )


def test_kb_policy_lookup_failure_denies_auto_reply(fake_db, make_state, use_db):
    """A DB outage during the policy lookup must deny auto-reply, not raise.
    This node is terminal, so raising yields no TrustSignals and core-api
    gets a 500 instead of a ticket it can route to a human.
    """

    db = fake_db(error=RuntimeError("connection refused"))
    use_db(db)
    node = emit_signals

    out = node(make_state(reranked=[_chunk(1, 0.9)], proposal=_auto_reply()))

    assert out["signals"].policy.kb_auto_reply_allowed is False
    assert out["signals"].policy.kb_risk_tier == "high"


def test_missing_kb_slug_denies_without_touching_the_database(fake_db, make_state, use_db):
    """No slug means there is nothing to look up — it must not be read as
    "policy check passed"."""

    db = fake_db(rows=[(True, "low")])
    use_db(db)
    node = emit_signals

    out = node(make_state(reranked=[_chunk(1, 0.9)]))

    assert out["signals"].policy.kb_auto_reply_allowed is False
    assert db.events == []


def test_docs_above_floor_uses_the_per_request_floor_from_state(fake_db, make_state, use_db):
    """`retrieval_floor` arrives per-request so core-api owns calibration. A
    floor read from local config would score tickets against a threshold
    that doesn't match core-api's recorded thresholds_used.
    """

    use_db(fake_db())

    node = emit_signals
    chunks = [_chunk(1, 0.9), _chunk(2, 0.6), _chunk(3, 0.2)]

    high = node(make_state(reranked=chunks, retrieval_floor=0.8))
    low = node(make_state(reranked=chunks, retrieval_floor=0.1))

    assert high["signals"].retrieval.docs_above_floor == 1
    assert low["signals"].retrieval.docs_above_floor == 3


def test_rerank_margin_is_zero_for_a_single_chunk(fake_db, make_state, use_db):
    """Margin is top1 - top2; with one chunk there is no second score.
    Reporting top1 itself as the margin would inflate the trust score on
    exactly the thin-evidence case the margin exists to catch."""

    use_db(fake_db())

    node = emit_signals

    out = node(make_state(reranked=[_chunk(1, 0.9)]))

    assert out["signals"].retrieval.rerank_margin == 0.0
    assert out["signals"].retrieval.rerank_top1 == 0.9


def test_no_reranked_chunks_yields_zeroed_retrieval_signals(fake_db, make_state, use_db):
    """The refuse-before-LLM and injection paths both arrive here with
    nothing retrieved. That must produce zeros, not a KeyError."""

    use_db(fake_db())

    node = emit_signals

    out = node(make_state())

    assert out["signals"].retrieval.rerank_top1 == 0.0
    assert out["signals"].retrieval.docs_above_floor == 0


def test_bm25_rank_is_none_when_nothing_was_reranked(fake_db, make_state, use_db):
    """Refuse-before-LLM and injection paths arrive with nothing reranked.
    Even if BM25 found articles, there is no top article to agree with, so
    reporting a rank would let core-api count agreement on a run that never
    chose an answer."""

    use_db(fake_db())

    out = emit_signals(make_state(bm25_article_ids=[UUID(int=10)]))

    assert out["signals"].retrieval.bm25_rank_of_top1 is None


def test_bm25_rank_is_none_when_the_top_article_is_absent_from_bm25(fake_db, make_state, use_db):
    """The disagreement case: the reranker chose an article BM25 never
    returned (g028's shape). That must be no rank, never a default of 1."""

    use_db(fake_db())

    out = emit_signals(make_state(reranked=[_chunk(1, 0.9)], bm25_article_ids=[UUID(int=99)]))

    assert out["signals"].retrieval.bm25_rank_of_top1 is None


def test_bm25_rank_is_the_one_based_position_of_the_top_article(fake_db, make_state, use_db):
    """Rank, not index: core-api compares it with `k` (rank <= k), so an
    off-by-one here shifts every agreement decision by one place."""

    use_db(fake_db())
    top = _chunk(1, 0.9)  # article UUID(int=10)

    out = emit_signals(
        make_state(reranked=[top, _chunk(2, 0.5)], bm25_article_ids=[UUID(int=7), UUID(int=10)])
    )

    assert out["signals"].retrieval.bm25_rank_of_top1 == 2


def test_ai_engine_cannot_send_the_legacy_keyword_flag():
    """core-api scores `legacy_flag or rank <= k`. If ai-engine ever sets the
    legacy flag again, agreement stops depending on `k` at all. The field
    lives only in core-api's copy (for signals stored before ADR-0013), so
    ai-engine has nothing to set it with."""

    assert "bm25_keyword_hit" not in RetrievalSignals.model_fields


def test_missing_validation_defaults_to_all_checks_failed(fake_db, make_state, use_db):
    """Refuse-before-LLM skips the validator. Absent validation must read as
    "the checks did not pass", never as "no checks were needed".
    """

    use_db(fake_db())

    node = emit_signals

    generation = node(make_state())["signals"].generation

    assert generation.schema_valid is False
    assert generation.quote_source_in_topk is False
    assert generation.negation_consistent is False
    assert generation.category_consistent is False
    assert generation.clarify_options_in_topk is False


def test_clarify_check_is_forwarded(fake_db, make_state, use_db):
    """core-api's router asks the question only on this signal (ADR-0016);
    left unforwarded it would read as failed and the branch would never fire."""
    use_db(fake_db())

    out = emit_signals(make_state(clarify_options_in_topk=True))

    assert out["signals"].generation.clarify_options_in_topk is True


def test_injection_verdict_is_forwarded_to_policy_signals(fake_db, make_state, use_db):
    use_db(fake_db())
    node = emit_signals

    out = node(make_state(injection_detected=True))

    assert out["signals"].policy.injection_detected is True


@pytest.mark.parametrize("level", [PIILevel.ROUTINE, PIILevel.SENSITIVE, PIILevel.CRITICAL])
def test_pii_level_is_carried_from_the_ticket(level, fake_db, make_state, make_ticket, use_db):
    use_db(fake_db())
    node = emit_signals
    ticket = make_ticket()
    ticket = ticket.model_copy(update={"pii_level": level})

    out = node(make_state(ticket=ticket))

    assert out["signals"].policy.pii_level == level


def test_policy_is_read_from_the_database_when_a_kb_slug_is_present(fake_db, make_state, use_db):
    """Companion to the outage test: with a reachable DB the node reports the
    KB row, so the outage test's False is attributable to the outage.
    """

    db = fake_db(rows=[(True, "low")])
    use_db(db)
    node = emit_signals

    out = node(make_state(reranked=[_chunk(1, 0.9)], proposal=_auto_reply()))

    assert db.events == ["open", "close"]
    assert out["signals"].policy.kb_auto_reply_allowed is True
    assert out["signals"].policy.kb_risk_tier == "low"


def test_signals_are_on_jevs_scale(fake_db, make_state, use_db):
    """Top-1, margin and the floor count are Jev's numbers, the scale the
    floor is set on; the cross-encoder's would score the ticket on one it
    isn't. `scorer` says so explicitly: core-api reads a missing value as
    the cross-encoder's."""

    use_db(fake_db())
    chunks = [
        _chunk(1, 0.2).model_copy(update={"rerank_score": 0.9}),
        _chunk(2, 0.9).model_copy(update={"rerank_score": 0.5}),
    ]

    out = emit_signals(make_state(reranked=chunks, retrieval_floor=0.6))

    retrieval = out["signals"].retrieval
    assert (retrieval.rerank_top1, retrieval.rerank_margin) == (0.9, pytest.approx(0.4))
    assert retrieval.docs_above_floor == 1
    assert retrieval.model_dump()["scorer"] == "jev"


def test_jevs_category_is_forwarded(fake_db, make_state, use_db):
    """The router takes this as the ticket's category (ADR-0017). Dropped
    here, it would read as "not asked" and send every route to a human."""

    from ai_engine.schemas import TicketCategory

    use_db(fake_db())

    out = emit_signals(make_state(category_choice=TicketCategory.NETWORK, category_confidence=0.77))

    classification = out["signals"].classification
    assert (classification.category_choice, classification.category_confidence) == (
        TicketCategory.NETWORK,
        0.77,
    )


def test_a_run_that_never_asked_jev_reports_no_category(fake_db, make_state, use_db):
    """The injection guard refuses before Jev: no category, which the router
    reads as "send to a human" wherever it needs one."""

    use_db(fake_db())

    out = emit_signals(make_state(injection_detected=True))

    assert out["signals"].classification.category_choice is None
    assert out["signals"].classification.category_confidence == 0.0
