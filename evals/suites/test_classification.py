"""
Classification F1 — spec §12.2 (`test_classification`, threshold: F1 >= 0.85
**per category**, not averaged — spec is explicit that an average hides a
rare-but-serious category like `security` scoring badly while the
aggregate still looks fine).

Live pipeline: the predicted category is Jev's choice,
`signals.classification.category_choice` (ADR-0017), the category the router
routes on. The LLM's `proposed_category` is log-only and not scored here.

Cases come from `kb_covered` AND `out_of_kb`. The demo KB is AWS
documentation, so no `other` ticket (HR, facilities) can be KB-covered.
Scoring only `kb_covered` would silently drop `other` from the
per-category gate, which CLAUDE.md rule 9 forbids. Out-of-KB tickets still
have a right category, and Jev chooses one for every ticket, below the
floor included (from the ticket alone, with no page). So the suite runs at
the real floor, as production does: Jev sees a page only when the ticket
has one above it, the condition the question was measured under
(evals/HISTORY.md 2026-10-04 (5)).

Before ADR-0017 the LLM chose the category, and an `insufficient_context`
refusal on an out-of-KB case was credited with the truth (decided
2026-09-29, evals/HISTORY-archive.md), since the LLM names no category when
it refuses. Jev always names one, so nothing is credited: a ticket with no
choice (a failed run) is a miss.
"""

from collections import defaultdict
from typing import Any

from suites.golden_utils import EVAL_FULL_RUN, analyze, load_golden, record_metric

F1_THRESHOLD = 0.85
PER_CATEGORY_SAMPLE = 5  # per category, not a flat slice — see _stratified_sample
# With F1's harsh small-n resolution (integer hit counts, no partial
# credit), a single miss out of fewer than ~4 samples mathematically
# cannot land above 0.85 even when the underlying error rate would
# comfortably clear it at scale. Categories with fewer than this many
# evaluated cases are reported but excluded from the hard gate — at
# EVAL_FULL_RUN=1 every category has 10 cases, well above this floor.
MIN_SAMPLES_TO_GATE = 5


def _predicted_category(result: dict[str, Any]) -> str | None:
    """Jev's choice, or None when the run asked no one (refused at the
    injection guard, or stored before ADR-0017)."""
    classification = (result.get("signals") or {}).get("classification") or {}
    return classification.get("category_choice")


def _stratified_sample(cases: list[dict], per_category: int) -> list[dict]:
    """A flat `cases[:n]` slice risks missing entire categories (the
    golden set is grouped by KB article, i.e. by category) — exactly the
    failure mode spec §12.2 calls out per-category F1 to catch. Sampling
    `per_category` cases from EACH category instead guarantees every
    category gets evaluated even at a small default sample size."""
    if EVAL_FULL_RUN:
        return cases
    by_category: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by_category[c["truth"]["category"]].append(c)
    return [c for bucket in by_category.values() for c in bucket[:per_category]]


def test_per_category_f1_meets_threshold(ai_engine_client):
    cases = _stratified_sample(
        [c for c in load_golden("kb_covered", "out_of_kb") if "category" in c["truth"]],
        PER_CATEGORY_SAMPLE,
    )
    assert cases

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for case in cases:
        truth = case["truth"]["category"]
        result = analyze(ai_engine_client, case["subject"], case["body"])
        predicted = _predicted_category(result)

        if predicted == truth:
            tp[truth] += 1
        else:
            fn[truth] += 1
            if predicted is not None:
                fp[predicted] += 1

    failing = {}
    per_category_f1 = {}
    for category in sorted(set(tp) | set(fp) | set(fn)):
        evaluated = tp[category] + fn[category]  # cases whose TRUTH is this category
        precision = (
            tp[category] / (tp[category] + fp[category]) if (tp[category] + fp[category]) else 0.0
        )
        recall = (
            tp[category] / (tp[category] + fn[category]) if (tp[category] + fn[category]) else 0.0
        )
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        gated = evaluated >= MIN_SAMPLES_TO_GATE
        note = (
            "" if gated else f"  (n={evaluated} < {MIN_SAMPLES_TO_GATE}, reported only, not gated)"
        )
        print(
            f"  category={category:10s} precision={precision:.2f} recall={recall:.2f} f1={f1:.2f}{note}"
        )
        per_category_f1[category] = f1
        if gated and f1 < F1_THRESHOLD:
            failing[category] = f1

    record_metric(
        "per_category_f1",
        min(per_category_f1.values()) if per_category_f1 else 0.0,
        by_category=per_category_f1,
    )
    assert not failing, f"categories below F1 {F1_THRESHOLD}: {failing}"
