"""
Record one eval run in evals/history/ (runs.jsonl + metrics.jsonl), the
machine-readable side of HISTORY.md. Run it after writing the HISTORY.md
entry, so the heading it points at exists:

    uv run --package evals python evals/record_run.py \\
        --id 2026-10-02-full --kind full_run \\
        --entry "2026-10-02: <the HISTORY.md heading, without '## '>" \\
        --title "Full run after ADR-0014" --duration 1065

By default it reads the suites' evals/.results.json. A probe passes its own
numbers with --metrics (a JSON list of {"metric", "value", "n"?, "labels"?,
"cases"?}). The configuration (commit, dirty files, golden and KB snapshot
hashes, prompt and graph versions, thresholds, models from the stack's
compose env file, --env-file, default infra/.env) is collected here; --set key=value adds or overrides an entry, e.g. the KB
counts, which need the database. --dry-run prints the rows instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from history import Metric, Run, RunKind, append, check, gate_for  # noqa: E402

EVALS = Path(__file__).parent
REPO = EVALS.parent
RESULTS = EVALS / ".results.json"
THRESHOLDS = REPO / "services/core-api/config/thresholds.yaml"
ENV_KEYS = (
    "CHAT_MODEL",
    "EMBED_MODEL",
    "RERANKER_MODEL",
    "RERANKER_REVISION",
    "VLLM_CHAT_MAX_MODEL_LEN",
    "VLLM_IMAGE_TAG",
)


def metrics_from_results(results: dict[str, Any], run_id: str) -> list[Metric]:
    """The suites' .results.json shapes, as tidy rows. Each suite records
    {"value", "n"?, ...extras}; the extras that are numbers of their own
    (MRR, gold_use, per-category F1) become rows of their own."""

    rows: list[Metric] = []

    def add(metric: str, value: float, n: int | None = None, **labels: str) -> None:
        rows.append(
            Metric(
                run=run_id, metric=metric, value=value, n=n, labels=labels, gate=gate_for(metric)
            )
        )

    for name, entry in results.items():
        if not isinstance(entry, dict):
            entry = {"value": entry}
        n = entry.get("n")
        if name in ("retrieval_recall_at_3", "retrieval_recall_at_5"):
            add("retrieval_recall_at_3", entry["value"], n)
            if "mrr" in entry:
                add("retrieval_mrr", entry["mrr"], n)
            for outcome, count in entry.get("gold_use", {}).items():
                add("gold_use", count, outcome=outcome)
        elif name == "per_category_f1":
            # The suite's headline "value" is the minimum; recording it as
            # its own row would invite averaging-style charts (rule 9).
            for category, f1 in entry.get("by_category", {}).items():
                add("category_f1", f1, category=category)
        else:
            add(name, entry["value"], n)
    return rows


def metrics_from_file(path: Path, run_id: str) -> list[Metric]:
    return [
        Metric(
            run=run_id, gate=gate_for(m["metric"]), **{k: v for k, v in m.items() if k != "gate"}
        )
        for m in json.loads(path.read_text(encoding="utf-8"))
    ]


def collect_config(env: Path) -> dict[str, str | int | float | bool | None]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()

    config: dict[str, str | int | float | bool | None] = {
        "code": git("rev-parse", "--short", "HEAD"),
        "dirty_files": len(git("status", "--porcelain").splitlines()),
        "golden": hashlib.sha256((EVALS / "golden/tickets.jsonl").read_bytes()).hexdigest()[:12],
        "kb_snapshot": json.loads((REPO / "demo_kb/manifest.json").read_text())["snapshot_sha256"][
            :12
        ],
    }
    try:
        from ai_engine.core.config import Settings

        config["prompt"] = Settings.model_fields["prompt_version"].default
        config["graph"] = Settings.model_fields["graph_version"].default
    except ImportError:
        pass
    thresholds = yaml.safe_load(THRESHOLDS.read_text())
    retrieval, routing = thresholds.get("retrieval", {}), thresholds.get("routing", {})
    for key in ("floor", "rerank_top_n", "keyword_agreement_k"):
        if key in retrieval:
            config[f"retrieval.{key}"] = retrieval[key]
    for key in ("t_auto", "t_route"):
        if key in routing:
            config[key] = routing[key]
    # The models the stack actually ran come from the compose env file, not
    # from ai-engine's defaults, which a deployment overrides.
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ENV_KEYS and value.strip():
                config[key.strip().lower()] = yaml.safe_load(value.strip())
    return config


def parse_set(pairs: list[str]) -> dict[str, str | int | float | bool | None]:
    out: dict[str, str | int | float | bool | None] = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        out[key] = yaml.safe_load(raw)  # 28519 -> int, 0.45 -> float, true -> bool
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--id", required=True, help="YYYY-MM-DD-slug, unique")
    p.add_argument("--kind", required=True, choices=[k.value for k in RunKind])
    p.add_argument("--entry", required=True, help="the HISTORY.md heading, without '## '")
    p.add_argument("--title", required=True)
    p.add_argument(
        "--results", type=Path, default=None, help=f"default {RESULTS.relative_to(REPO)}"
    )
    p.add_argument("--metrics", type=Path, default=None, help="probe metrics, a JSON list")
    p.add_argument("--duration", type=float, default=None, help="seconds")
    p.add_argument("--notes", default=None)
    p.add_argument(
        "--env-file",
        type=Path,
        default=REPO / "infra/.env",
        help="the stack's compose env, for model names (default infra/.env)",
    )
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    metrics: list[Metric] = []
    if a.metrics:
        metrics += metrics_from_file(a.metrics, a.id)
    if a.results or not a.metrics:
        path = a.results or RESULTS
        metrics += metrics_from_results(json.loads(path.read_text()), a.id)

    run = Run(
        id=a.id,
        date=date.fromisoformat(a.id[:10]),
        kind=RunKind(a.kind),
        title=a.title,
        history_entry=a.entry,
        source="recorder",
        config=collect_config(a.env_file) | parse_set(a.set),
        duration_s=a.duration,
        notes=a.notes,
    )
    if a.dry_run:
        print(run.model_dump_json(exclude_none=True))
        for m in metrics:
            print(m.model_dump_json(exclude_defaults=True))
        problems = check(run, metrics)
        print("\n".join(f"problem: {x}" for x in problems) or "ok", file=sys.stderr)
        return
    append(run, metrics)
    print(f"recorded {run.id}: {len(metrics)} metrics", file=sys.stderr)


if __name__ == "__main__":
    main()
