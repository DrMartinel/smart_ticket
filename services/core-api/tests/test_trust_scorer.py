"""
Trust scorer — spec §7 / ADR-0003. The one property that MUST hold no
matter how the underlying model is recalibrated: llm_self_confidence is
never part of the feature set.
"""

from contracts.enums import PIILevel
from contracts.trust import GenerationSignals, PolicySignals, RetrievalSignals, TrustSignals

from apps.tickets.services.trust_scorer import FEATURES, extract_features, score


def make_signals(**overrides) -> TrustSignals:
    s = TrustSignals(
        retrieval=RetrievalSignals(rerank_top1=0.9, rerank_margin=0.3, bm25_keyword_hit=True, docs_above_floor=3),
        generation=GenerationSignals(
            schema_valid=True, quote_match_ratio=1.0, quote_source_in_topk=True,
            negation_consistent=True, category_consistent=True,
        ),
        policy=PolicySignals(
            kb_auto_reply_allowed=True, kb_risk_tier="low", pii_level=PIILevel.ROUTINE,
            injection_detected=False, mass_incident=False,
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
