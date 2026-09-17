"""
Injection recall — spec §12.2 (`test_injection`, threshold: recall >= 0.95).

Runs fully offline: ai_engine's injection detector is pure regex over
text, no DB/LLM/network involved, so this suite always runs, unlike the
live-pipeline suites.
"""

from ai_engine.core.state import TriageState
from ai_engine.graph.nodes.injection import InjectionNode
from contracts.enums import PIILevel
from contracts.ticket import TicketMasked

from suites.golden_utils import load_golden, record_metric

RECALL_THRESHOLD = 0.95

# Constructed once: the detector does no I/O, so this is free.
_NODE = InjectionNode()


def _detect(subject: str, body: str) -> bool:
    # The detector reads only the ticket; the remaining required TriageState
    # inputs are filler.
    state = TriageState(
        ticket=TicketMasked(
            ticket_public_id="TKT-EVAL",
            subject_masked=subject,
            body_masked=body,
            pii_level=PIILevel.ROUTINE,
            placeholder_keys=[],
        ),
        request_id="eval",
        retrieval_floor=0.0,
        max_tokens=1,
        max_llm_calls=1,
        max_latency_sec=1,
        max_graph_iterations=1,
        tokens_used=0,
        llm_calls=0,
        started_at=0.0,
        iteration=0,
    )
    return _NODE(state)["injection_detected"]


def test_injection_recall_meets_threshold():
    cases = load_golden("injection")
    assert cases, "golden set has no injection-tagged cases"

    caught = sum(1 for c in cases if _detect(c["subject"], c["body"]))
    recall = caught / len(cases)

    record_metric("injection_recall", recall, n=len(cases))
    assert recall >= RECALL_THRESHOLD, (
        f"injection recall {recall:.2%} < {RECALL_THRESHOLD:.0%} threshold "
        f"({caught}/{len(cases)} caught)"
    )


def test_ordinary_tickets_are_not_false_flagged():
    # A detector that flags everything trivially hits 100% recall — this
    # guards against that degenerate case using the kb_covered set, which
    # contains no injection attempts by construction.
    cases = load_golden("kb_covered")[:20]
    false_positives = [c["id"] for c in cases if _detect(c["subject"], c["body"])]
    assert not false_positives, (
        f"false-positive injection flags on ordinary tickets: {false_positives}"
    )
