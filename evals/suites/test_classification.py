"""
Classification F1 — spec §12.2 (`test_classification`, threshold: F1 >= 0.85
**per category**, not averaged — spec is explicit that an average hides a
rare-but-serious category like `security` scoring badly while the
aggregate still looks fine).

Live pipeline: predicted category comes from whichever proposal field
carries it (`RouteProposal.proposed_category`, `RunbookProposal.
proposed_category`), or — for an `auto_reply` proposal — the retrieved
KB article's own category via `retrieved_chunks[0].kb_slug`, since
AutoReplyProposal doesn't carry a category field of its own.

Cases come from `kb_covered` AND `out_of_kb`. The demo KB is AWS
documentation, so no `other` ticket (HR, facilities) can be KB-covered.
Scoring only `kb_covered` would silently drop `other` from the
per-category gate, which CLAUDE.md rule 9 forbids. Out-of-KB tickets still
have a right category. The pipeline would refuse them before the LLM, but
this suite runs with `never_refuse=True` (floor 0.0), so the model always answers.

On an out-of-KB case, `insufficient_context` counts as correct (decided
2026-09-29, evals/HISTORY-archive.md). It names no category, but it is the answer
spec §12.2 asks for when the KB has nothing on the topic, and
test_refusal.py scores it correct on these same cases. Scoring it wrong
here would demand the opposite of the refusal suite, and push the prompt
towards confident routing on exactly the tickets an HR request that slips
over the floor would be. What the `other` gate protects is that such a
ticket is never claimed as an IT category or auto-replied: those still
count against `other` and as a false positive for the category claimed.
On a KB-covered case, a refusal is still a miss.
"""

from collections import defaultdict
from typing import Any

from suites.golden_utils import EVAL_FULL_RUN, analyze, kb_category, load_golden, record_metric

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
    proposal = result.get("proposal") or {}
    intent = proposal.get("proposed_intent")
    if intent in ("route_to_team", "runbook", "clarify"):
        return proposal.get("proposed_category")
    if intent == "auto_reply":
        chunks = result.get("retrieved_chunks") or []
        slug = chunks[0]["kb_slug"] if chunks else proposal.get("kb_slug")
        return kb_category(slug) if isinstance(slug, str) else None
    return None


def _scored_category(case: dict[str, Any], result: dict[str, Any]) -> str | None:
    """The category this answer is credited with. A refusal on an
    out-of-KB case is credited with the truth (module docstring). Only an
    explicit `insufficient_context` counts: a run with no proposal at all
    (schema invalid, degraded) is a failure, not a refusal."""

    proposal = result.get("proposal") or {}
    if "out_of_kb" in case["tags"] and proposal.get("proposed_intent") == "insufficient_context":
        return str(case["truth"]["category"])
    return _predicted_category(result)


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
        result = analyze(ai_engine_client, case["subject"], case["body"], never_refuse=True)
        predicted = _scored_category(case, result)

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
