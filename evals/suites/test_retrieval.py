"""
Retrieval quality — spec §12.2: recall@5 >= 0.90 on the `kb_covered` tickets,
a hit on the gold page or an acceptable one.

Calls ai-engine's /v1/analyze with `never_refuse=True` and reads
`retrieved_chunks`, so a refusal by the model is not a retrieval miss. Also
reports, ungated: recall@3 (recorded as `retrieval_recall_at_5` before
2026-09-29), strict recall@3, MRR, the cross-encoder's batch (`pool_size`),
what the model did with the gold article (`_gold_use`), and the tickets
answered with a 5xx, each counted as a miss. A 4xx or an unreachable
ai-engine fails the run.
"""

from statistics import median

import httpx

from suites.golden_utils import analyze, load_golden, record_metric, sample

RECALL_THRESHOLD = 0.90
# The gated k: the proposal is shown Jev's top RERANK_TOP_N chunks (spec §12.2).
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
    print(
        f"Cross-encoder batch: median={median(pool_sizes or [0])} max={max(pool_sizes, default=0)}"
    )
    record_metric(
        "retrieval_recall_at_3",
        recall,
        mrr=mrr,
        strict=recall_strict,
        n=len(cases),
        gold_use={k: len(v) for k, v in gold_use.items()},
        # Every ticket can error (a reranker outage): report 0, not crash.
        pool_size_median=median(pool_sizes or [0]),
        pool_size_max=max(pool_sizes, default=0),
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
