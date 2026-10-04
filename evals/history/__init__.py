"""
Machine-readable eval history: the numbers behind `evals/HISTORY.md`, in a
shape charts and reports can load directly.

HISTORY.md says what a measurement meant; these two files hold what it was:

  runs.jsonl     one line per run: date, kind, the HISTORY.md heading it is
                 recorded under, and the configuration that produced it
  metrics.jsonl  one line per number ("tidy" data): run, metric, value, n,
                 labels, the gate in force when it was measured, and the
                 golden case ids behind it where they matter

Runs from before the current baseline live in archive/ with the same two
files, under HISTORY-archive.md's headings. They are read-only: the
recorder only appends to the current files.

A metric's name must be in `METRICS`, so a chart can rely on its unit,
direction and gate, and new names can't drift in unnoticed. Rows are
appended, never edited: a later correction is a new run, like a HISTORY.md
entry. `evals/record_run.py` writes them; `suites/test_history_data.py`
fails CI when the data and HISTORY.md disagree.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HERE = Path(__file__).parent
RUNS_PATH = HERE / "runs.jsonl"
METRICS_PATH = HERE / "metrics.jsonl"
HISTORY_MD = HERE.parent / "HISTORY.md"
ARCHIVE_RUNS_PATH = HERE / "archive" / "runs.jsonl"
ARCHIVE_METRICS_PATH = HERE / "archive" / "metrics.jsonl"
HISTORY_ARCHIVE_MD = HERE.parent / "HISTORY-archive.md"


class RunKind(StrEnum):
    # Every suite, EVAL_FULL_RUN=1: the only kind a baseline can come from.
    FULL_RUN = "full_run"
    # Some suites on the full golden set, e.g. the retrieval suite alone.
    SUITE_RUN = "suite_run"
    # Outside the suites: production nodes driven by a script to test a
    # design. Comparable within the run, never a gate measurement.
    PROBE = "probe"


class Gate(BaseModel):
    """The pass condition in force when a number was measured. Stored per
    row, not looked up later, so a chart of an old run shows the gate that
    run faced even after a gate changes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[">=", "<="]
    value: float
    basis: str  # where the number comes from: a spec section, baseline.json

    def passes(self, value: float) -> bool:
        return value >= self.value if self.op == ">=" else value <= self.value


class MetricSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit: Literal["ratio", "count", "seconds", "score"]
    # None where neither direction is better (a distribution of outcomes).
    higher_is_better: bool | None
    description: str
    gate: Gate | None = None
    # Label keys a row may carry, besides `variant`, which any row may.
    labels: tuple[str, ...] = ()


_RECALL_GATE = Gate(op=">=", value=0.90, basis="spec §12.2, test_retrieval")
_PROBE_LABELS = ("pool", "seeds", "k", "order", "scorer")

METRICS: dict[str, MetricSpec] = {
    # --- gated by the eval suites -------------------------------------------
    "retrieval_recall_at_3": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        gate=_RECALL_GATE,
        labels=_PROBE_LABELS,
        description="KB-covered tickets whose gold article is among the rerank_top_n (3) "
        "pages returned. Recorded as retrieval_recall_at_5 before 2026-09-29; same measure.",
    ),
    "auto_reply_precision": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        gate=Gate(op=">=", value=0.95, basis="spec §12.3, absolute"),
        description="Of tickets routed to auto_reply, the share whose golden branch is auto_reply.",
    ),
    "injection_recall": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        gate=Gate(op=">=", value=1.0, basis="baseline.json, no drop allowed"),
        description="Injection tickets caught by the injection guard.",
    ),
    "refusal_rate": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        gate=Gate(op=">=", value=0.90, basis="spec §12.2, test_refusal"),
        description="Out-of-KB tickets correctly refused (insufficient_context, or top-1 below the floor).",
    ),
    "quote_validation_precision": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        gate=Gate(op=">=", value=0.95, basis="spec §12.2, test_quote_validation"),
        description="Hand-crafted hallucinated or mis-negated quotes the validator flags.",
    ),
    "category_f1": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=("category",),
        gate=Gate(op=">=", value=0.85, basis="spec §12.3, every category"),
        description="Per-category F1 of the classification suite. Never averaged (rule 9).",
    ),
    # --- reported, not gated ------------------------------------------------
    "flag_auroc": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=("flag", "kind"),
        description="How well a scored flag (e.g. Jev's multi_issue noul) separates golden "
        "tickets of one kind from the clear kb_covered tickets. 0.5 is chance.",
    ),
    "masking_pii_level_accuracy": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        description="PII cases whose mask() level matches expected_pii_level, over every "
        "pass of the masking suite. Over-masked tickets are mask_failed, so wrong.",
    ),
    "masking_overmask_rate": MetricSpec(
        unit="ratio",
        higher_is_better=False,
        description="Ticket-passes where NER covered more than masking.ner_max_share of "
        "the text beyond the regex hits (masking suite, every golden ticket).",
    ),
    "masking_consistency": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        description="Golden tickets that masked identically on every pass of the masking suite.",
    ),
    "branch_accuracy": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        description="Tickets whose routed branch matches the golden branch (end-to-end suite).",
    ),
    "category_precision": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=("category",),
        description="Per-category precision of the classification suite.",
    ),
    "category_recall": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=("category",),
        description="Per-category recall of the classification suite.",
    ),
    "retrieval_recall_at_k": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="Gold article among the k chunks a variant would show the classify model "
        "(label k). Not comparable with retrieval_recall_at_3 unless k is 3; no gate.",
    ),
    "retrieval_mrr": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="Mean reciprocal rank of the gold article in the returned pages.",
    ),
    "gold_use": MetricSpec(
        unit="count",
        higher_is_better=None,
        labels=("outcome",),
        description="Retrieval hits by what the model did with the gold article: "
        "quoted, quote_missed, refused, other (test_retrieval).",
    ),
    # --- retrieval probes ---------------------------------------------------
    "misses_recovered": MetricSpec(
        unit="count",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="Baseline retrieval misses a variant gets right; `cases` lists them.",
    ),
    "cases_lost": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=_PROBE_LABELS,
        description="Cases the baseline got right that a variant gets wrong; `cases` lists them.",
    ),
    "article_hit_at_k": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=("representation", "k"),
        description="Gold article within the top k of an article-level ranking of the whole KB.",
    ),
    "chunks_reranked_median": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=_PROBE_LABELS,
        description="Median chunks the cross-encoder scores per ticket.",
    ),
    "chunks_reranked_max": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=_PROBE_LABELS,
        description="Most chunks the cross-encoder scores for one ticket.",
    ),
    "oob_above_floor": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=_PROBE_LABELS,
        description="Out-of-KB tickets whose top-1 cross-encoder score clears retrieval.floor.",
    ),
    "oob_top1_max": MetricSpec(
        unit="score",
        higher_is_better=False,
        labels=_PROBE_LABELS,
        description="Highest top-1 cross-encoder score among out-of-KB tickets.",
    ),
    "gold_chunk_score": MetricSpec(
        unit="score",
        higher_is_better=True,
        labels=("case",),
        description="Cross-encoder score of the gold article's best chunk.",
    ),
    "third_place_score": MetricSpec(
        unit="score",
        higher_is_better=None,
        labels=("case",),
        description="Cross-encoder score of the page in 3rd place, the bar the gold chunk must clear.",
    ),
    "refusal_separation_auroc": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="How well each ticket's top-1 score separates the out-of-KB tickets from the "
        "KB-covered ones (1.0 = every KB-covered ticket scores above every out-of-KB one).",
    ),
    "kb_refused_at_safe_threshold": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=_PROBE_LABELS,
        description="KB-covered tickets a threshold just above the highest out-of-KB top-1 score "
        "would refuse; `cases` lists them. A measure of the gap, not a chosen floor.",
    ),
    "rerank_margin_median": MetricSpec(
        unit="score",
        higher_is_better=None,
        labels=_PROBE_LABELS,
        description="Median top-1 minus top-2 score on the 0-1 scale the trust signals use "
        "(sigmoid of log-odds for an LLM reranker).",
    ),
    "auroc_gold_vs_rest": MetricSpec(
        unit="ratio",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="How well a scorer separates the gold page from the other pages above the floor.",
    ),
    "gold_ranked_first": MetricSpec(
        unit="count",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="Tickets where a scorer ranks the gold page first among pages above the floor.",
    ),
    "first_pick_consistency": MetricSpec(
        unit="count",
        higher_is_better=True,
        labels=_PROBE_LABELS,
        description="Tickets where an LLM re-orderer's first pick is the same whichever order "
        "the passages are shown in.",
    ),
    "model_calls": MetricSpec(
        unit="count",
        higher_is_better=None,
        labels=("component",),
        description="Calls made to a model in a probe.",
    ),
    "invalid_outputs": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=("component",),
        description="Model outputs rejected as invalid (and replaced by the fallback).",
    ),
    "passages_truncated": MetricSpec(
        unit="count",
        higher_is_better=False,
        labels=("component",),
        description="Passages cut to fit a model's context.",
    ),
    "latency_p50_s": MetricSpec(
        unit="seconds",
        higher_is_better=False,
        labels=("component",),
        description="Median latency of one call to a component.",
    ),
    "latency_p95_s": MetricSpec(
        unit="seconds",
        higher_is_better=False,
        labels=("component",),
        description="95th-percentile latency of one call to a component.",
    ),
}


class Run(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
    date: date
    kind: RunKind
    title: str
    # The HISTORY.md heading this run is recorded under, without "## ".
    history_entry: str
    # "transcribed" for runs typed in from HISTORY.md before this data
    # existed; "recorder" for runs written by record_run.py.
    source: Literal["recorder", "transcribed"]
    # Pinned inputs: code, golden, kb_snapshot at least; models, prompt,
    # graph and thresholds where known. Free-form keys, scalar values.
    config: dict[str, str | int | float | bool | None]
    duration_s: float | None = None
    notes: str | None = None


class Metric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run: str
    metric: str
    value: float
    n: int | None = None
    labels: dict[str, str] = {}
    gate: Gate | None = None
    cases: list[str] = []

    @property
    def passed(self) -> bool | None:
        return None if self.gate is None else self.gate.passes(self.value)


REQUIRED_CONFIG = ("code", "golden", "kb_snapshot")


def load_runs(path: Path = RUNS_PATH) -> list[Run]:
    return [Run.model_validate_json(line) for line in _lines(path)]


def load_metrics(path: Path = METRICS_PATH) -> list[Metric]:
    return [Metric.model_validate_json(line) for line in _lines(path)]


def append(
    run: Run,
    metrics: Iterable[Metric],
    *,
    runs_path: Path = RUNS_PATH,
    metrics_path: Path = METRICS_PATH,
) -> None:
    """Append one run and its metrics after checking them; refuses a run id
    that already exists, since rows are never edited."""

    metrics = list(metrics)
    if any(r.id == run.id for r in load_runs(runs_path)):
        raise ValueError(f"run {run.id!r} already recorded; record a new run instead")
    problems = check(run, metrics)
    if problems:
        raise ValueError("; ".join(problems))
    with runs_path.open("a", encoding="utf-8") as f:
        f.write(run.model_dump_json(exclude_none=True) + "\n")
    with metrics_path.open("a", encoding="utf-8") as f:
        for m in metrics:
            f.write(m.model_dump_json(exclude_defaults=True) + "\n")


def check(run: Run, metrics: list[Metric]) -> list[str]:
    """Problems that make a run unusable for charts; empty when it is fine."""

    problems = [f"config lacks {k!r}" for k in REQUIRED_CONFIG if k not in run.config]
    if not metrics:
        problems.append("no metrics")
    for m in metrics:
        spec = METRICS.get(m.metric)
        if m.run != run.id:
            problems.append(f"{m.metric}: run {m.run!r} is not {run.id!r}")
        if spec is None:
            problems.append(f"unknown metric {m.metric!r}: add it to METRICS first")
            continue
        extra = set(m.labels) - set(spec.labels) - {"variant"}
        if extra:
            problems.append(f"{m.metric}: unexpected labels {sorted(extra)}")
        if spec.unit == "ratio" and not 0.0 <= m.value <= 1.0:
            problems.append(f"{m.metric}: ratio {m.value} outside [0, 1]")
    return problems


def gate_for(metric: str) -> Gate | None:
    spec = METRICS.get(metric)
    return spec.gate if spec else None


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
