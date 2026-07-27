"""
Trust Scorer — spec §7. Deliberately in core-api, not ai-engine, so the
LLM has zero influence over the score used to judge its own output
(ADR-0003, ADR-0004).

`FEATURES` is exactly the 8 features listed in the spec. Note what's
absent: `llm_self_confidence`. That's not an oversight — see ADR-0003.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from contracts.trust import TrustScore, TrustSignals

FEATURES = [
    "rerank_top1",
    "rerank_margin",
    "bm25_keyword_hit",
    "docs_above_floor_capped",  # min(n, 3) / 3
    "quote_match_ratio",
    "quote_source_in_topk",
    "negation_consistent",
    "category_consistent",
]
# CHÚ Ý: llm_self_confidence is NOT in this list. On purpose. See ADR-0003.

_MODEL_PATH = Path(settings.BASE_DIR) / "config" / "trust_model_v0.json"


@lru_cache(maxsize=1)
def _load_model() -> dict:
    with open(_MODEL_PATH) as f:
        return json.load(f)


def extract_features(signals: TrustSignals) -> dict[str, float]:
    r, g = signals.retrieval, signals.generation
    return {
        "rerank_top1": r.rerank_top1,
        "rerank_margin": r.rerank_margin,
        "bm25_keyword_hit": 1.0 if r.bm25_keyword_hit else 0.0,
        "docs_above_floor_capped": min(r.docs_above_floor, 3) / 3.0,
        "quote_match_ratio": g.quote_match_ratio,
        "quote_source_in_topk": 1.0 if g.quote_source_in_topk else 0.0,
        "negation_consistent": 1.0 if g.negation_consistent else 0.0,
        "category_consistent": 1.0 if g.category_consistent else 0.0,
    }


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def score(signals: TrustSignals) -> TrustScore:
    model = _load_model()
    x = extract_features(signals)

    z = model["intercept"]
    contributions: dict[str, float] = {}
    for feat in FEATURES:
        w = model["weights"][feat]
        contribution = w * x[feat]
        z += contribution
        contributions[feat] = round(contribution, 4)

    p = _sigmoid(z)

    return TrustScore(
        value=round(p, 4),
        model_version=model["model_version"],
        contributions=contributions,
    )
