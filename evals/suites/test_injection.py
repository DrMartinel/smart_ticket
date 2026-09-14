"""
Injection recall — spec §12.2 (`test_injection`, threshold: recall >= 0.95).

Runs fully offline: ai_engine's injection detector is pure regex over
text, no DB/LLM/network involved, so this suite always runs, unlike the
live-pipeline suites.
"""

from ai_engine.graph.nodes.injection import InjectionNode

_NODE = InjectionNode()
from contracts.enums import PIILevel
from contracts.ticket import TicketMasked

from suites.golden_utils import load_golden, record_metric

RECALL_THRESHOLD = 0.95


def _detect(subject: str, body: str) -> bool:
    state = {
        "ticket": TicketMasked(
            ticket_public_id="TKT-EVAL", subject_masked=subject, body_masked=body,
            pii_level=PIILevel.ROUTINE, placeholder_keys=[],
        )
    }
    return _NODE(state)["injection"]["detected"]


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
    assert not false_positives, f"false-positive injection flags on ordinary tickets: {false_positives}"
