"""
Masking — core-api's `mask()` on every golden ticket, through the live NER
tier (ai-engine's `/v1/pii/detect`), several passes per ticket.

Three numbers, all reported, none gated yet (there is no baseline to hold):
- `masking_pii_level_accuracy`: tickets whose level matches the golden
  `expected_pii_level`, over the PII cases and every pass. An over-masked
  ticket is MASK_FAILED in production, so it counts as wrong here too.
- `masking_overmask_rate`: ticket-passes where NER covered more than
  `masking.ner_max_share` of the text beyond the regex hits. NER has masked
  whole non-PII sentences, an injection among them (evals/HISTORY.md
  2026-10-04 (2)); this is how often.
- `masking_consistency`: tickets that masked identically on every pass.
  Below 1.0, the same ticket gets a different masked text from run to run.

The level is what routing acts on, and the masked text is all ai-engine and
the injection detector ever see, so both are measured as production makes
them: through `mask()` itself, not a copy of its rules.
"""

from __future__ import annotations

import os
import statistics

from asgiref.sync import async_to_sync
from django.conf import settings

from apps.tickets.request_schema import TicketIn
from apps.tickets.utils.masking import mask
from suites.golden_utils import load_golden, record_metric, sample

# NER runs at temperature 0 since pii_ner.v2, so passes should agree; more
# than one is what shows whether they do.
PASSES = int(os.environ.get("EVAL_MASKING_PASSES", "3"))


def test_masking_level_overmasking_and_consistency(ai_engine_client):
    max_share = settings.THRESHOLDS.masking.ner_max_share
    cases = sample(load_golden())

    level_right = level_total = 0
    overmasked: dict[str, int] = {}
    inconsistent: list[str] = []
    shares: list[float] = []

    for case in cases:
        raw = TicketIn(subject=case["subject"], body=case["body"])
        expected = case["truth"].get("expected_pii_level")
        outputs = set()
        for _ in range(PASSES):
            result = async_to_sync(mask)(raw, max_share)
            outputs.add((result.subject_masked, result.body_masked))
            shares.append(result.ner_share)
            if result.ner_share > max_share:
                overmasked[case["id"]] = overmasked.get(case["id"], 0) + 1
            if expected is not None:
                level_total += 1
                level_right += result.pii_level.value == expected
        if len(outputs) > 1:
            inconsistent.append(case["id"])

    ticket_passes = len(cases) * PASSES
    accuracy = level_right / level_total if level_total else None
    overmask_rate = sum(overmasked.values()) / ticket_passes
    consistency = 1 - len(inconsistent) / len(cases)

    print(
        f"\nMasking: passes={PASSES} n={len(cases)} pii_level_accuracy={accuracy} "
        f"overmask_rate={overmask_rate:.3f} overmasked={overmasked} "
        f"consistency={consistency:.3f} inconsistent={inconsistent} "
        f"ner_share mean={statistics.fmean(shares):.3f} max={max(shares):.3f}"
    )
    if accuracy is not None:
        record_metric("masking_pii_level_accuracy", accuracy, n=level_total)
    record_metric("masking_overmask_rate", overmask_rate, n=ticket_passes)
    record_metric("masking_consistency", consistency, n=len(cases))
