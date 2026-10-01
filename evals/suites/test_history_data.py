"""
The machine-readable eval history (evals/history/) stays usable for charts
and stays in step with HISTORY.md. Offline: no model, no database.

Without these, the failure is quiet: a chart silently drops a run whose
metric name drifted, a HISTORY.md entry gets no numbers behind it, or a
number is recorded under a run nobody can trace back to its configuration.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from history import HISTORY_MD, METRICS, Run, check, load_metrics, load_runs

sys.path.insert(0, str(Path(__file__).parents[1]))
from record_run import metrics_from_results  # noqa: E402

HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}.*)$", re.MULTILINE)


@pytest.fixture(scope="module")
def runs() -> list[Run]:
    return load_runs()


def test_every_run_passes_the_registry_checks(runs):
    """Unknown metric names, stray labels, ratios outside [0, 1] or a missing
    commit/golden/KB pin make a run unusable for charts or untraceable."""

    metrics = load_metrics()
    problems = {r.id: check(r, [m for m in metrics if m.run == r.id]) for r in runs}
    assert not {k: v for k, v in problems.items() if v}


def test_run_ids_are_unique_and_every_metric_belongs_to_a_run(runs):
    ids = [r.id for r in runs]
    assert len(ids) == len(set(ids))
    orphans = {m.run for m in load_metrics()} - set(ids)
    assert not orphans, f"metrics for unrecorded runs: {orphans}"


def test_runs_are_appended_in_date_order(runs):
    """Rows are appended, never edited or inserted; a run dated before the
    last one means a file was rewritten."""

    dates = [r.date for r in runs]
    assert dates == sorted(dates)


def test_every_run_points_at_a_history_entry(runs):
    headings = set(HEADING.findall(HISTORY_MD.read_text(encoding="utf-8")))
    missing = {r.id: r.history_entry for r in runs if r.history_entry not in headings}
    assert not missing, f"runs whose HISTORY.md heading does not exist: {missing}"


def test_every_history_entry_has_data(runs):
    """A new HISTORY.md entry has to be recorded with record_run.py too,
    or the report built from the data silently misses it."""

    recorded = {r.history_entry for r in runs}
    entries = HEADING.findall(HISTORY_MD.read_text(encoding="utf-8"))
    assert [e for e in entries if e not in recorded] == []


def test_results_json_shapes_become_tidy_rows():
    """The suites' .results.json shapes, as written by record_metric: the
    extras that are numbers of their own become rows of their own, and the
    classification suite's headline minimum is not recorded as a row, so no
    chart can present a single "F1" for all categories (rule 9)."""

    rows = metrics_from_results(
        {
            "retrieval_recall_at_3": {
                "value": 0.78,
                "mrr": 0.69,
                "n": 60,
                "gold_use": {"quoted": 38, "refused": 0},
            },
            "per_category_f1": {"value": 0.89, "by_category": {"access": 0.9, "other": 0.95}},
            "auto_reply_precision": {"value": 0.95, "n": 21},
        },
        "2026-10-02-x",
    )
    got = {(r.metric, tuple(sorted(r.labels.items())), r.value, r.n) for r in rows}
    assert got == {
        ("retrieval_recall_at_3", (), 0.78, 60),
        ("retrieval_mrr", (), 0.69, 60),
        ("gold_use", (("outcome", "quoted"),), 38, None),
        ("gold_use", (("outcome", "refused"),), 0, None),
        ("category_f1", (("category", "access"),), 0.9, None),
        ("category_f1", (("category", "other"),), 0.95, None),
        ("auto_reply_precision", (), 0.95, 21),
    }
    assert all(r.metric in METRICS for r in rows)
    gated = {r.metric: r.gate for r in rows}
    assert gated["auto_reply_precision"] is not None and gated["auto_reply_precision"].value == 0.95


def test_old_metric_name_maps_to_the_renamed_one():
    """retrieval_recall_at_5 measured exactly what retrieval_recall_at_3 does
    (HISTORY.md, 2026-09-29 (3)); a results file using the old name must not
    become a second, disconnected series."""

    rows = metrics_from_results({"retrieval_recall_at_5": {"value": 0.72, "n": 60}}, "2026-10-02-x")
    assert [r.metric for r in rows] == ["retrieval_recall_at_3"]
