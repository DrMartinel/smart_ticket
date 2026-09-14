"""
Trust scorer — spec §7 / ADR-0003. The one property that MUST hold no
matter how the underlying model is recalibrated: llm_self_confidence is
never part of the feature set.
"""

from contracts.enums import PIILevel
from contracts.trust import GenerationSignals, PolicySignals, RetrievalSignals, TrustSignals

from apps.tickets.services.trust_scorer import (
    FEATURES,
    QUOTE_FEATURES,
    extract_features,
    score,
    scored_features,
)


def make_signals(**overrides) -> TrustSignals:
    s = TrustSignals(
        retrieval=RetrievalSignals(
            rerank_top1=0.9, rerank_margin=0.3, bm25_keyword_hit=True, docs_above_floor=3
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
    assert score(s1).value == score(s2).value


def test_score_is_deterministic():
    s = make_signals()
    assert score(s).value == score(s).value


def test_higher_retrieval_quality_yields_higher_score():
    weak = make_signals(**{"retrieval.rerank_top1": 0.2, "retrieval.rerank_margin": 0.0})
    strong = make_signals(**{"retrieval.rerank_top1": 0.95, "retrieval.rerank_margin": 0.4})
    assert score(strong).value > score(weak).value


def test_score_bounded_in_unit_interval():
    result = score(make_signals())
    assert 0.0 <= result.value <= 1.0


def test_contributions_present_for_every_feature():
    result = score(make_signals())
    assert set(result.contributions.keys()) == set(FEATURES)


def test_extract_features_covers_all_declared_features():
    x = extract_features(make_signals())
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

        assert score(skipped).value == score(scored).value

    def test_contributions_omit_inapplicable_features(self):
        s = make_signals()
        s.generation.quote_applicable = False
        contributions = score(s).contributions
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
