"""
Retrieval quality — spec §12.2 (`test_retrieval`, threshold: recall >= 0.90).

The spec calls this Recall@5, but the pipeline returns `rerank_top_n` = 3
chunks, so what is measured is Recall@3 and the metric is named for that.
Until 2026-09-29 it was recorded as `retrieval_recall_at_5`; see
evals/HISTORY-archive.md before comparing numbers across the rename.

Live pipeline: calls ai-engine's /v1/analyze with `retrieval_floor=0.0` so
the graph never refuses before returning chunks, then checks
`retrieved_chunks` (the actual post-rerank output) directly — this
measures RETRIEVAL quality specifically, independent of what the LLM
subsequently decided to do with those chunks (a model that retrieved the
right article but still said "insufficient_context" is a generation
problem, not a retrieval miss).

It also reports, ungated, what the model did with the gold article when
retrieval found it (`_gold_use`). The golden set has no expected quote, so
this is a proxy for "the chunk kept for the gold article held the answer":
since per-article dedup (rerank.py) the LLM sees one chunk per article, and
if that chunk only restates the problem the model can refuse or quote text
it wasn't shown.
"""

from suites.golden_utils import analyze, load_golden, record_metric, sample

RECALL_THRESHOLD = 0.90


def _gold_use(result: dict, truth_slug: str) -> str:
    """What the model did with a gold article that was in its context:
    `quoted` (auto-reply on it, quote found in the chunks shown),
    `quote_missed` (auto-reply on it, quote not in the chunks shown),
    `refused` (insufficient_context despite the gold article), or `other`
    (a route/runbook proposal, an auto-reply on another article, or no
    proposal), which says nothing about the kept chunk."""

    proposal = result.get("proposal") or {}
    intent = proposal.get("proposed_intent")
    if intent == "insufficient_context":
        return "refused"
    if intent == "auto_reply" and proposal.get("kb_slug") == truth_slug:
        in_topk = result["signals"]["generation"]["quote_source_in_topk"]
        return "quoted" if in_topk else "quote_missed"
    return "other"


def test_recall_and_mrr_on_kb_covered_cases(ai_engine_client):
    cases = sample(load_golden("kb_covered"))
    hits = 0
    reciprocal_ranks = []
    misses = []
    gold_use: dict[str, list[str]] = {"quoted": [], "quote_missed": [], "refused": [], "other": []}

    for case in cases:
        result = analyze(ai_engine_client, case["subject"], case["body"], retrieval_floor=0.0)
        truth_slug = case["truth"]["kb_slug"]
        retrieved_slugs = [c["kb_slug"] for c in result.get("retrieved_chunks", [])]

        if truth_slug in retrieved_slugs:
            hits += 1
            rank = retrieved_slugs.index(truth_slug) + 1
            reciprocal_ranks.append(1 / rank)
            gold_use[_gold_use(result, truth_slug)].append(case["id"])
        else:
            reciprocal_ranks.append(0.0)
            misses.append((case["id"], truth_slug, retrieved_slugs))

    recall = hits / len(cases)
    mrr = sum(reciprocal_ranks) / len(cases)

    print(f"\nRetrieval: recall={recall:.2%} mrr={mrr:.3f} n={len(cases)} misses={misses}")
    print(f"Gold article in context ({hits}): {gold_use}")
    record_metric(
        "retrieval_recall_at_3",
        recall,
        mrr=mrr,
        n=len(cases),
        gold_use={k: len(v) for k, v in gold_use.items()},
    )
    assert recall >= RECALL_THRESHOLD, (
        f"recall {recall:.2%} < {RECALL_THRESHOLD:.0%}, misses={misses}"
    )
