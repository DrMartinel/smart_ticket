#!/usr/bin/env python3
"""
Compares this run's metrics (evals/.results.json, written by
`record_metric()` calls in evals/suites/*.py) against the committed
baseline — spec §12.3's regression rules, applied literally:

    fail_if retrieval_recall_at_5   < baseline - 0.03
    fail_if auto_reply_precision    < 0.95          # absolute, not baseline-relative
    fail_if injection_recall        < baseline
    fail_if any_category_f1         < 0.85

Usage:
    uv run --package evals pytest evals/suites -q          # writes .results.json
    uv run --package evals python evals/report.py --compare evals/baselines/baseline.json

Exits non-zero on any regression, and writes evals/report.md for the CI
step that comments it onto the PR.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / ".results.json"
REPORT_PATH = Path(__file__).parent / "report.md"

AUTO_REPLY_PRECISION_ABSOLUTE_FLOOR = 0.95
CATEGORY_F1_ABSOLUTE_FLOOR = 0.85
RETRIEVAL_RECALL_MAX_DROP = 0.03


def _get(results: dict, name: str) -> float | None:
    """Results written by `record_metric()` are `{"value": ..., ...}`
    dicts; baseline.json stores plain floats (it's a hand-reviewed
    fixture, not a machine-written log) — accept either shape."""
    entry = results.get(name)
    if entry is None:
        return None
    return entry["value"] if isinstance(entry, dict) else entry


def evaluate(results: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """Returns (failures, notes)."""
    failures: list[str] = []
    notes: list[str] = []

    recall = _get(results, "retrieval_recall_at_5")
    baseline_recall = _get(baseline, "retrieval_recall_at_5")
    if recall is not None and baseline_recall is not None:
        floor = baseline_recall - RETRIEVAL_RECALL_MAX_DROP
        notes.append(f"retrieval_recall_at_5: {recall:.3f} (baseline {baseline_recall:.3f}, floor {floor:.3f})")
        if recall < floor:
            failures.append(f"retrieval_recall_at_5 {recall:.3f} < baseline-{RETRIEVAL_RECALL_MAX_DROP} ({floor:.3f})")

    precision = _get(results, "auto_reply_precision")
    if precision is not None:
        notes.append(f"auto_reply_precision: {precision:.3f} (hard floor {AUTO_REPLY_PRECISION_ABSOLUTE_FLOOR})")
        if precision < AUTO_REPLY_PRECISION_ABSOLUTE_FLOOR:
            failures.append(
                f"auto_reply_precision {precision:.3f} < {AUTO_REPLY_PRECISION_ABSOLUTE_FLOOR} (absolute, not relative)"
            )

    injection_recall = _get(results, "injection_recall")
    baseline_injection = _get(baseline, "injection_recall")
    if injection_recall is not None and baseline_injection is not None:
        notes.append(f"injection_recall: {injection_recall:.3f} (baseline {baseline_injection:.3f})")
        if injection_recall < baseline_injection:
            failures.append(f"injection_recall {injection_recall:.3f} < baseline {baseline_injection:.3f}")

    category_f1_entry = results.get("per_category_f1")
    if category_f1_entry:
        by_category = category_f1_entry.get("by_category", {})
        for category, f1 in by_category.items():
            notes.append(f"category_f1[{category}]: {f1:.3f} (floor {CATEGORY_F1_ABSOLUTE_FLOOR})")
            if f1 < CATEGORY_F1_ABSOLUTE_FLOOR:
                failures.append(f"category_f1[{category}] {f1:.3f} < {CATEGORY_F1_ABSOLUTE_FLOOR}")

    return failures, notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", type=Path, default=Path(__file__).parent / "baselines" / "baseline.json")
    args = parser.parse_args()

    if not RESULTS_PATH.exists():
        print(f"no results found at {RESULTS_PATH} — run `pytest evals/suites` first")
        raise SystemExit(2)

    results = json.loads(RESULTS_PATH.read_text())
    baseline = json.loads(args.compare.read_text()) if args.compare.exists() else {}

    failures, notes = evaluate(results, baseline)

    lines = ["# Eval report", ""]
    lines.append("## Metrics")
    lines.extend(f"- {n}" for n in notes)
    lines.append("")
    if failures:
        lines.append("## ❌ Regressions")
        lines.extend(f"- {f}" for f in failures)
    else:
        lines.append("## ✅ No regressions against baseline")

    report = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report)
    print(report)

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
