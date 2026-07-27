"""
Retrieval quality — spec §12.2 (`test_retrieval`, threshold: Recall@5 >= 0.90).

Live pipeline: calls ai-engine's /v1/analyze with `retrieval_floor=0.0` so
the graph never refuses before returning chunks, then checks
`retrieved_chunks` (the actual post-rerank output) directly — this
measures RETRIEVAL quality specifically, independent of what the LLM
subsequently decided to do with those chunks (a model that retrieved the
right article but still said "insufficient_context" is a generation
problem, not a retrieval miss).
"""

from suites.golden_utils import analyze, load_golden, record_metric, sample

RECALL_THRESHOLD = 0.90


def test_recall_and_mrr_on_kb_covered_cases(ai_engine_client):
    cases = sample(load_golden("kb_covered"))
    hits = 0
    reciprocal_ranks = []
    misses = []

    for case in cases:
        result = analyze(ai_engine_client, case["subject"], case["body"], retrieval_floor=0.0)
        truth_slug = case["truth"]["kb_slug"]
        retrieved_slugs = [c["kb_slug"] for c in result.get("retrieved_chunks", [])]

        if truth_slug in retrieved_slugs:
            hits += 1
            rank = retrieved_slugs.index(truth_slug) + 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)
            misses.append((case["id"], truth_slug, retrieved_slugs))

    recall = hits / len(cases)
    mrr = sum(reciprocal_ranks) / len(cases)

    print(f"\nRetrieval: recall={recall:.2%} mrr={mrr:.3f} n={len(cases)} misses={misses}")
    record_metric("retrieval_recall_at_5", recall, mrr=mrr, n=len(cases))
    assert recall >= RECALL_THRESHOLD, f"recall {recall:.2%} < {RECALL_THRESHOLD:.0%}, misses={misses}"
