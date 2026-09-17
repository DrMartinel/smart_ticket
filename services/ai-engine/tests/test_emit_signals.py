"""
Terminal-node tests. Every path through the graph ends here, so this node
failing is not a degraded answer — it is no answer at all.
"""

from __future__ import annotations

import pytest

from contracts.enums import PIILevel
from contracts.llm_draft import AutoReplyProposal, LLMProposalEnvelope

from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.core.retrieval.rerank import RankedChunk


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
        chunk_id=chunk_id,
        article_id=chunk_id * 10,
        article_slug=slug,
        content="nội dung",
        score=score,
    )


def test_kb_policy_lookup_failure_denies_auto_reply(fake_db, make_state):
    """A DB outage during the policy lookup must deny auto-reply, not raise.
    This node is terminal, so raising yields no TrustSignals and core-api
    gets a 500 instead of a ticket it can route to a human.
    """

    db = fake_db(error=RuntimeError("connection refused"))
    node = EmitSignalsNode(db=db)

    out = node(make_state(reranked=[_chunk(1, 0.9)], proposal=_auto_reply()))

    assert out["signals"].policy.kb_auto_reply_allowed is False
    assert out["signals"].policy.kb_risk_tier == "high"


def test_missing_kb_slug_denies_without_touching_the_database(fake_db, make_state):
    """No slug means there is nothing to look up — it must not be read as
    "policy check passed"."""

    db = fake_db(rows=[(True, "low")])
    node = EmitSignalsNode(db=db)

    out = node(make_state(reranked=[_chunk(1, 0.9)]))

    assert out["signals"].policy.kb_auto_reply_allowed is False
    assert db.events == []


def test_docs_above_floor_uses_the_per_request_floor_from_state(fake_db, make_state):
    """`retrieval_floor` arrives per-request so core-api owns calibration. A
    floor read from local config would score tickets against a threshold
    that doesn't match core-api's recorded thresholds_used.
    """

    node = EmitSignalsNode(db=fake_db())
    chunks = [_chunk(1, 0.9), _chunk(2, 0.6), _chunk(3, 0.2)]

    high = node(make_state(reranked=chunks, retrieval_floor=0.8))
    low = node(make_state(reranked=chunks, retrieval_floor=0.1))

    assert high["signals"].retrieval.docs_above_floor == 1
    assert low["signals"].retrieval.docs_above_floor == 3


def test_rerank_margin_is_zero_for_a_single_chunk(fake_db, make_state):
    """Margin is top1 - top2; with one chunk there is no second score.
    Reporting top1 itself as the margin would inflate the trust score on
    exactly the thin-evidence case the margin exists to catch."""

    node = EmitSignalsNode(db=fake_db())

    out = node(make_state(reranked=[_chunk(1, 0.9)]))

    assert out["signals"].retrieval.rerank_margin == 0.0
    assert out["signals"].retrieval.rerank_top1 == 0.9


def test_no_reranked_chunks_yields_zeroed_retrieval_signals(fake_db, make_state):
    """The refuse-before-LLM and injection paths both arrive here with
    nothing retrieved. That must produce zeros, not a KeyError."""

    node = EmitSignalsNode(db=fake_db())

    out = node(make_state())

    assert out["signals"].retrieval.rerank_top1 == 0.0
    assert out["signals"].retrieval.docs_above_floor == 0
    assert out["signals"].retrieval.topk_chunk_ids == []


def test_missing_validation_defaults_to_all_checks_failed(fake_db, make_state):
    """Refuse-before-LLM skips the validator. Absent validation must read as
    "the checks did not pass", never as "no checks were needed".
    """

    node = EmitSignalsNode(db=fake_db())

    generation = node(make_state())["signals"].generation

    assert generation.schema_valid is False
    assert generation.quote_source_in_topk is False
    assert generation.negation_consistent is False
    assert generation.category_consistent is False


def test_injection_verdict_is_forwarded_to_policy_signals(fake_db, make_state):
    node = EmitSignalsNode(db=fake_db())

    out = node(make_state(injection_detected=True))

    assert out["signals"].policy.injection_detected is True


@pytest.mark.parametrize("level", [PIILevel.ROUTINE, PIILevel.SENSITIVE, PIILevel.CRITICAL])
def test_pii_level_is_carried_from_the_ticket(level, fake_db, make_state, make_ticket):
    node = EmitSignalsNode(db=fake_db())
    ticket = make_ticket()
    ticket = ticket.model_copy(update={"pii_level": level})

    out = node(make_state(ticket=ticket))

    assert out["signals"].policy.pii_level == level


def test_policy_is_read_from_the_database_when_a_kb_slug_is_present(fake_db, make_state):
    """Companion to the outage test: with a reachable DB the node reports the
    KB row, so the outage test's False is attributable to the outage.
    """

    db = fake_db(rows=[(True, "low")])
    node = EmitSignalsNode(db=db)

    out = node(make_state(reranked=[_chunk(1, 0.9)], proposal=_auto_reply()))

    assert db.events == ["open", "close"]
    assert out["signals"].policy.kb_auto_reply_allowed is True
    assert out["signals"].policy.kb_risk_tier == "low"
