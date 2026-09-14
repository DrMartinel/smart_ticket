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
"""

from collections import defaultdict

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

# slug -> category, mirrors seed_demo.py — used only to resolve category
# for auto_reply proposals in this suite, not by the system under test.
_SLUG_CATEGORY = {
    "KB-0001": "access",
    "KB-0002": "hardware",
    "KB-0003": "network",
    "KB-0004": "access",
    "KB-0005": "software",
    "KB-0006": "access",
    "KB-0007": "hardware",
    "KB-0008": "software",
    "KB-0009": "security",
    "KB-0010": "other",
    "KB-0011": "hardware",
    "KB-0012": "software",
}


def _predicted_category(result: dict) -> str | None:
    proposal = result.get("proposal") or {}
    intent = proposal.get("proposed_intent")
    if intent in ("route_to_team", "runbook"):
        return proposal.get("proposed_category")
    if intent == "auto_reply":
        chunks = result.get("retrieved_chunks") or []
        slug = chunks[0]["kb_slug"] if chunks else proposal.get("kb_slug")
        return _SLUG_CATEGORY.get(slug)
    return None


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
        [c for c in load_golden("kb_covered") if "category" in c["truth"]], PER_CATEGORY_SAMPLE
    )
    assert cases

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for case in cases:
        truth = case["truth"]["category"]
        result = analyze(ai_engine_client, case["subject"], case["body"], retrieval_floor=0.0)
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
