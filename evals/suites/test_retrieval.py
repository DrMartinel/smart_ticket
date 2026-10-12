"""
Retrieval quality — spec §12.2 (`test_retrieval`, threshold: recall >= 0.90).

The spec calls this Recall@5, but the pipeline returns `rerank_top_n` = 3
chunks, so what is measured is Recall@3 and the metric is named for that.
Until 2026-09-29 it was recorded as `retrieval_recall_at_5`; see
evals/HISTORY-archive.md before comparing numbers across the rename.

Live pipeline: calls ai-engine's /v1/analyze with `never_refuse=True` (floor 0.0) so
the graph never refuses before returning chunks, then checks
`retrieved_chunks` (the actual post-rerank output) directly — this
measures RETRIEVAL quality specifically, independent of what the LLM
subsequently decided to do with those chunks (a model that retrieved the
right article but still said "insufficient_context" is a generation
problem, not a retrieval miss).

It also reports, ungated, two things. The cross-encoder's batch per ticket
(`pool_size`, median and max): link expansion's cost, which the ADR-0018
eval plan compares across association sources. And what the model did with
the gold article when retrieval found it (`_gold_use`). The golden set has no expected quote, so
this is a proxy for "the chunk kept for the gold article held the answer":
since per-article dedup (the rerank node) the LLM sees one chunk per article, and
if that chunk only restates the problem the model can refuse or quote text
it wasn't shown.

A ticket ai-engine answers with a 5xx (a failed draft, a Jev or DeepSeek
outage) counts as a miss and is listed in `errors`: in production it goes to
a person with no retrieval, so it can only lower recall, never raise it. One
such ticket used to abort the whole 500-ticket run with no score. Anything
else (a 4xx, ai-engine unreachable) still fails the run: those are harness or
stack faults, not tickets.
"""

from statistics import median

import httpx

from suites.golden_utils import analyze, load_golden, record_metric, sample

RECALL_THRESHOLD = 0.90
# The gate is recall@5, as spec §12.2 names it: the proposal is shown Jev's
# top RERANK_TOP_N (5) chunks. Recall@3 is still reported, ungated.
GATED_K = 5


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
    strict_hits = 0
    reciprocal_ranks = []
    misses = []
    gold_use: dict[str, list[str]] = {"quoted": [], "quote_missed": [], "refused": [], "other": []}
    pool_sizes: list[int] = []
    errors: list[str] = []
    hits_at_5 = 0
    top_n = 0

    for case in cases:
        try:
            result = analyze(ai_engine_client, case["subject"], case["body"], never_refuse=True)
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise
            errors.append(case["id"])
            reciprocal_ranks.append(0.0)
            misses.append((case["id"], case["truth"]["kb_slug"], ["<error>"]))
            continue
        pool_sizes.append(result["signals"]["retrieval"]["pool_size"])
        truth_slug = case["truth"]["kb_slug"]
        # Pages that answer the ticket as well as its gold page
        # (`acceptable_kb_slugs`, SCHEMA.md): a hit on one is a hit.
        accepted = [truth_slug, *case["truth"].get("acceptable_kb_slugs", [])]
        shown = [c["kb_slug"] for c in result.get("retrieved_chunks", [])]
        # Recall@3 reads the first 3 whatever RERANK_TOP_N is; a run with
        # RERANK_TOP_N 5 also reports recall@5 (spec §12.2 names @5).
        retrieved_slugs = shown[:3]
        hits_at_5 += any(s in accepted for s in shown[:5])
        top_n = max(top_n, len(shown))
        strict_hits += truth_slug in retrieved_slugs

        found = next((s for s in retrieved_slugs if s in accepted), None)
        if found is not None:
            hits += 1
            rank = retrieved_slugs.index(found) + 1
            reciprocal_ranks.append(1 / rank)
            gold_use[_gold_use(result, found)].append(case["id"])
        else:
            reciprocal_ranks.append(0.0)
            misses.append((case["id"], truth_slug, retrieved_slugs))

    recall = hits / len(cases)
    recall_strict = strict_hits / len(cases)
    mrr = sum(reciprocal_ranks) / len(cases)

    print(
        f"\nRetrieval: recall={recall:.2%} strict={recall_strict:.2%} mrr={mrr:.3f} "
        f"n={len(cases)} errors={errors} misses={misses}"
    )
    if top_n >= 5:
        print(f"Recall@5: {hits_at_5 / len(cases):.2%}")
    print(f"Gold article in context ({hits}): {gold_use}")
    print(f"Cross-encoder batch: median={median(pool_sizes)} max={max(pool_sizes)}")
    record_metric(
        "retrieval_recall_at_3",
        recall,
        mrr=mrr,
        strict=recall_strict,
        n=len(cases),
        gold_use={k: len(v) for k, v in gold_use.items()},
        pool_size_median=median(pool_sizes),
        pool_size_max=max(pool_sizes),
        errors=len(errors),
        **({"recall_at_5": hits_at_5 / len(cases)} if top_n >= 5 else {}),
    )
    assert top_n >= GATED_K, (
        f"the gate is recall@{GATED_K} but the pipeline showed {top_n} chunks: "
        f"set RERANK_TOP_N >= {GATED_K}"
    )
    recall_at_5 = hits_at_5 / len(cases)
    assert recall_at_5 >= RECALL_THRESHOLD, (
        f"recall@5 {recall_at_5:.2%} < {RECALL_THRESHOLD:.0%}, misses@3={misses}"
    )
