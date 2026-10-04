"""
Trust scorer — spec §7 / ADR-0003. The one property that MUST hold no
matter how the underlying model is recalibrated: llm_self_confidence is
never part of the feature set.
"""

from apps.tickets.utils.patterns import PIILevel
from infrastructure.dtos import (
    ClassificationSignals,
    GenerationSignals,
    PolicySignals,
    RetrievalSignals,
    TicketCategory,
    TrustSignals,
)

import pytest
from pydantic import ValidationError

from config.settings.base import RetrievalThresholds
from apps.tickets.utils.trust_scorer import (
    FEATURES,
    QUOTE_FEATURES,
    extract_features,
    keyword_agreement,
    score,
    scored_features,
)


K = 3  # retrieval.keyword_agreement_k, as thresholds.yaml sets it


def make_signals(**overrides) -> TrustSignals:
    s = TrustSignals(
        retrieval=RetrievalSignals(
            rerank_top1=0.9, rerank_margin=0.3, bm25_rank_of_top1=1, docs_above_floor=3
        ),
        generation=GenerationSignals(
            schema_valid=True,
            quote_match_ratio=1.0,
            quote_source_in_topk=True,
            negation_consistent=True,
            category_consistent=True,
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
        llm_self_confidence=99.0,
    )
    for path, value in overrides.items():
        group, field = path.split(".")
        setattr(getattr(s, group), field, value)
    return s


def test_llm_self_confidence_excluded_from_features():
    assert "llm_self_confidence" not in FEATURES


def test_llm_self_confidence_does_not_change_score():
    s1 = make_signals()
    s1.llm_self_confidence = 99.0
    s2 = make_signals()
    s2.llm_self_confidence = 1.0
    assert score(s1, K).value == score(s2, K).value


def test_score_is_deterministic():
    s = make_signals()
    assert score(s, K).value == score(s, K).value


def test_higher_retrieval_quality_yields_higher_score():
    weak = make_signals(**{"retrieval.rerank_top1": 0.2, "retrieval.rerank_margin": 0.0})
    strong = make_signals(**{"retrieval.rerank_top1": 0.95, "retrieval.rerank_margin": 0.4})
    assert score(strong, K).value > score(weak, K).value


def test_score_bounded_in_unit_interval():
    result = score(make_signals(), K)
    assert 0.0 <= result.value <= 1.0


def test_contributions_present_for_every_feature():
    result = score(make_signals(), K)
    assert set(result.contributions.keys()) == set(FEATURES)


def test_extract_features_covers_all_declared_features():
    x = extract_features(make_signals(), K)
    assert set(x.keys()) == set(FEATURES)


class TestQuoteFeaturesOnlyScoredWhenApplicable:
    """A route/runbook proposal carries no verbatim quote, so the validator
    reports quote_match_ratio=0.0 and quote_source_in_topk=False for it.

    This change is about EXPLAINABILITY, not scoring — and the distinction
    matters enough to pin down. Because both features are linear terms
    (`w * value`), a value of 0.0 contributes exactly 0.0 whether it is
    summed or skipped, so excluding them cannot move the score. What it
    changes is `contributions`: the two features no longer appear at all,
    which lets the UI render "not applicable" instead of a red ✗ that
    reads as a failed check.

    The separate, real question — whether a route proposal should be
    judged on its own feature set and its own calibrated curve rather
    than sharing auto-reply's — is a P2 calibration decision (see
    docs/TODO.md), not something to change silently here.
    """

    def test_quote_features_skipped_when_not_applicable(self):
        s = make_signals()
        s.generation.quote_applicable = False
        assert set(scored_features(s)) == set(FEATURES) - set(QUOTE_FEATURES)

    def test_quote_features_scored_when_applicable(self):
        s = make_signals()
        s.generation.quote_applicable = True
        assert scored_features(s) == list(FEATURES)

    def test_skipping_zero_valued_features_does_not_move_the_score(self):
        """Guards the reasoning above: if someone later gives these
        features a non-zero baseline or a bias term, this test fails and
        forces a deliberate decision instead of a silent score shift."""
        scored = make_signals()
        scored.generation.quote_applicable = True
        scored.generation.quote_match_ratio = 0.0
        scored.generation.quote_source_in_topk = False

        skipped = make_signals()
        skipped.generation.quote_applicable = False
        skipped.generation.quote_match_ratio = 0.0
        skipped.generation.quote_source_in_topk = False

        assert score(skipped, K).value == score(scored, K).value

    def test_contributions_omit_inapplicable_features(self):
        s = make_signals()
        s.generation.quote_applicable = False
        contributions = score(s, K).contributions
        for feat in QUOTE_FEATURES:
            assert feat not in contributions, (
                f"{feat} must be absent from contributions so the UI can show "
                "'not applicable' rather than an unexplained silent penalty"
            )

    def test_defaults_to_applicable_for_older_persisted_signals(self):
        """Signals persisted before the flag existed deserialize without it;
        they must keep their original scoring behavior."""
        s = make_signals()
        assert s.generation.quote_applicable is True


# --- keyword agreement (ADR-0013) ----------------------------------------------


def test_rank_none_is_no_agreement():
    """None covers "BM25 never returned the top article" and "nothing was
    reranked". Both are the weak-evidence cases; treating None as agreement
    would raise trust exactly where one channel saw nothing."""

    assert keyword_agreement(make_signals(**{"retrieval.bm25_rank_of_top1": None}), K) is False


def test_agreement_holds_at_k_and_not_at_k_plus_one():
    """The boundary is `rank <= k`. `<` would quietly make k=3 behave as
    k=2, and nothing but this test would show it."""

    at_k = make_signals(**{"retrieval.bm25_rank_of_top1": K})
    past_k = make_signals(**{"retrieval.bm25_rank_of_top1": K + 1})

    assert keyword_agreement(at_k, K) is True
    assert keyword_agreement(past_k, K) is False


def test_agreement_raises_trust():
    """The feature must reach the score, in the direction that makes sense.
    A pinned weight would not survive recalibration; the direction must."""

    agree = make_signals(**{"retrieval.bm25_rank_of_top1": 1})
    disagree = make_signals(**{"retrieval.bm25_rank_of_top1": None})

    assert score(agree, K).value > score(disagree, K).value


def test_old_signals_without_a_rank_score_on_their_legacy_flag():
    """Signals stored before ADR-0013 have no rank field. They must load and
    score as they did (hard rule 4), not silently lose their flag."""

    stored = make_signals().model_dump(mode="json")
    del stored["retrieval"]["bm25_rank_of_top1"]
    stored["retrieval"]["bm25_keyword_hit"] = True

    old = TrustSignals(**stored)

    assert old.retrieval.bm25_rank_of_top1 is None
    assert keyword_agreement(old, K) is True


def test_thresholds_without_keyword_agreement_k_fail_to_load():
    """No Python default: a thresholds.yaml missing the key must fail at
    boot, not score trust with a number nobody chose (hard rule 2)."""

    with pytest.raises(ValidationError, match="keyword_agreement_k"):
        RetrievalThresholds(  # type: ignore[call-arg]  # the missing key is the test
            floor=0.30,
            margin=0.08,
            bm25_top_k=20,
            vector_top_k=20,
            rrf_k=60,
            rerank_top_n=3,
        )


def test_thresholds_without_a_floor_fail_to_load():
    """No Python default: a floor nobody chose would gate every ticket's
    refuse-before-LLM decision (hard rule 2)."""

    with pytest.raises(ValidationError, match="floor"):
        RetrievalThresholds(  # type: ignore[call-arg]  # the missing key is the test
            margin=0.08,
            bm25_top_k=20,
            vector_top_k=20,
            rrf_k=60,
            rerank_top_n=3,
            keyword_agreement_k=3,
        )
