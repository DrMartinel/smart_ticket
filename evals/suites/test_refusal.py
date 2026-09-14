"""
Refusal correctness — spec §12.2 (`test_refusal`, threshold: correctly
refuses on out-of-KB cases >= 0.90). "Refuse" means the model either
returns `insufficient_context`, or the retrieval floor gate itself would
reject it (rerank_top1 below the real, non-zero floor) — either is a
correct refusal; what's WRONG is a confident `auto_reply`/`route_to_team`
proposal on a topic the KB has nothing to say about.
"""

from suites.golden_utils import analyze, load_golden, sample

REFUSAL_THRESHOLD = 0.90
REAL_RETRIEVAL_FLOOR = 0.45  # spec §13 default


def _correctly_refused(result: dict) -> bool:
    proposal = result.get("proposal") or {}
    if proposal.get("proposed_intent") == "insufficient_context":
        return True
    top1 = result["signals"]["retrieval"]["rerank_top1"]
    return top1 < REAL_RETRIEVAL_FLOOR


def test_refusal_rate_on_out_of_kb_cases(ai_engine_client):
    cases = sample(load_golden("out_of_kb"))
    correct = 0
    wrong = []

    for case in cases:
        # retrieval_floor=0.0 so we see the model's actual behavior
        # end-to-end rather than the graph refusing before the LLM is
        # even called — we're testing refusal judgment, not the floor gate.
        result = analyze(ai_engine_client, case["subject"], case["body"], retrieval_floor=0.0)
        if _correctly_refused(result):
            correct += 1
        else:
            wrong.append((case["id"], result.get("proposal")))

    rate = correct / len(cases)
    print(f"\nRefusal rate: {rate:.2%} ({correct}/{len(cases)}), wrong={wrong}")
    assert rate >= REFUSAL_THRESHOLD, (
        f"refusal rate {rate:.2%} < {REFUSAL_THRESHOLD:.0%}, wrong={wrong}"
    )
