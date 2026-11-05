#!/usr/bin/env python3
"""
Sweeps `retrieval.min_rerank_confidence` over the golden set.

`collect` runs each golden ticket through ai-engine once, as the end-to-end
suite does, and saves what the router needs. `sweep` replays core-api's
`Router` over those saved runs at each bar, with every other threshold as
`thresholds.yaml` has it, and reports auto-reply precision and recall.

Usage:
    uv run --package evals python evals/calibration/sweep_rerank_confidence.py collect
    uv run --package evals python evals/calibration/sweep_rerank_confidence.py sweep \\
        evals/calibration/sweeps/<run>.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import django
import httpx

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
os.environ.setdefault("EMBEDDING_PROVIDER", "stub")
django.setup()

from django.conf import settings  # noqa: E402

from apps.kb.models import KbArticle  # noqa: E402
from apps.tickets.utils.patterns import PIILevel  # noqa: E402
from apps.tickets.utils.pipeline import trust_signals  # noqa: E402
from apps.tickets.utils.router import Branch, KBArticleMeta, RiskTier, Router  # noqa: E402
from infrastructure.dtos import EngineSignals, LLMProposalEnvelope, TicketCategory  # noqa: E402
from suites.golden_utils import AI_ENGINE_URL, analyze, load_golden  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)

SWEEPS = Path(__file__).parent / "sweeps"
AUTO_REPLY_PRECISION_FLOOR = 0.95
DEFAULT_BARS = "0.5,0.6,0.65,0.7,0.75,0.8,0.85,0.9,0.95"


def kb_meta_of(proposal: dict | None) -> dict | None:
    """The active KB page an auto-reply proposal names, as `KBArticleMeta` fields."""
    if not proposal or proposal.get("proposed_intent") != "auto_reply":
        return None
    kb = KbArticle.objects.filter(slug=proposal.get("kb_slug"), is_active=True).first()
    if kb is None:
        return None
    return {
        "id": str(kb.id),
        "slug": kb.slug,
        "category": kb.category,
        "auto_reply_allowed": kb.auto_reply_allowed,
        "risk_tier": kb.risk_tier,
    }


def run_case(client: httpx.Client, case: dict) -> dict:
    """One golden ticket's ai-engine result, or the status it failed with."""
    row: dict = {"id": case["id"], "truth": case["truth"], "tags": case["tags"]}
    try:
        result = analyze(client, case["subject"], case["body"])
    except httpx.HTTPStatusError as e:
        row["error"] = e.response.status_code
        return row
    except httpx.HTTPError as e:
        row["error"] = type(e).__name__
        return row
    row.update(
        pii_level=result["pii_level"],
        signals=result["signals"],
        proposal=result.get("proposal"),
        kb=kb_meta_of(result.get("proposal")),
    )
    return row


def collect(out: Path, workers: int, limit: int | None) -> None:
    """Runs every golden ticket not yet in `out` and appends its result."""
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {
            json.loads(line)["id"]
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip() and "error" not in json.loads(line)
        }
    cases = [c for c in load_golden() if c["truth"].get("expected_branch") and c["id"] not in done]
    if limit is not None:
        cases = cases[:limit]
    print(f"{len(done)} already collected, {len(cases)} to run → {out}")
    client = httpx.Client(base_url=AI_ENGINE_URL, timeout=180.0)
    lock = threading.Lock()
    finished = 0

    def one(case: dict) -> None:
        nonlocal finished
        row = run_case(client, case)
        with lock, out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            finished += 1
            if "error" in row or finished % 25 == 0:
                print(f"  {finished}/{len(cases)} {row['id']} {row.get('error', '')}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, cases))
    client.close()


def load_rows(path: Path) -> list[dict]:
    """The latest row per golden id, errors included."""
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["id"] not in rows or "error" in rows[row["id"]]:
                rows[row["id"]] = row
    return list(rows.values())


def router_at(bar: float) -> Router:
    """`thresholds.yaml` with `min_rerank_confidence` set to `bar`."""
    th = settings.THRESHOLDS
    retrieval = th.retrieval.model_copy(update={"min_rerank_confidence": bar})
    return Router(th.model_copy(update={"retrieval": retrieval}))


def decide(router: Router, row: dict):
    """The router's decision on one saved run."""
    kb = row["kb"]
    meta = (
        KBArticleMeta(
            id=kb["id"],
            slug=kb["slug"],
            category=TicketCategory(kb["category"]),
            auto_reply_allowed=kb["auto_reply_allowed"],
            risk_tier=RiskTier(kb["risk_tier"]),
        )
        if kb
        else None
    )
    proposal = LLMProposalEnvelope(root=row["proposal"]) if row["proposal"] else None
    signals = trust_signals(
        EngineSignals(**row["signals"]), PIILevel(row["pii_level"]), meta, clarifications_asked=0
    )
    return router.route(signals, proposal, meta)


def right_page(row: dict) -> bool:
    """Whether the cited page is the case's gold page or one of its acceptable pages."""
    truth = row["truth"]
    pages = {truth.get("kb_slug"), *truth.get("acceptable_kb_slugs", [])} - {None}
    return (row["proposal"] or {}).get("kb_slug") in pages


def sweep(path: Path, bars: list[float]) -> str:
    """The precision and recall table at each bar, as Markdown."""
    rows = load_rows(path)
    ran = [r for r in rows if "error" not in r]
    errors = [r["id"] for r in rows if "error" in r]
    expected = [r for r in ran if r["truth"]["expected_branch"] == "auto_reply"]
    current = settings.THRESHOLDS.retrieval.min_rerank_confidence
    lines = [
        f"# `min_rerank_confidence` sweep, {path.name}",
        "",
        f"{len(ran)} golden tickets ran ({len(errors)} errors, counted as no auto-reply); "
        f"{len(expected)} expect an auto-reply. Every other threshold as in "
        f"`thresholds.yaml` (version {settings.THRESHOLDS.version}); the bar there is {current}.",
        "",
        "Precision counts an auto-reply right when the case expects one (the end-to-end "
        "suite's rule); *page precision* also needs the cited page to be the gold page or an "
        f"acceptable one. Floor: {AUTO_REPLY_PRECISION_FLOOR}.",
        "",
        "| Bar | Auto-replies | Right | Precision | Page precision | Recall | Wrong |",
        "|---|---|---|---|---|---|---|",
    ]
    for bar in bars:
        router = router_at(bar)
        sent = [r for r in ran if decide(router, r).branch is Branch.AUTO_REPLY]
        right = [r for r in sent if r["truth"]["expected_branch"] == "auto_reply"]
        page_right = [r for r in right if right_page(r)]
        wrong = sorted(r["id"] for r in sent if r not in page_right)
        precision = len(right) / len(sent) if sent else float("nan")
        page_precision = len(page_right) / len(sent) if sent else float("nan")
        recall = len(page_right) / len(expected) if expected else float("nan")
        mark = " (current)" if bar == current else ""
        lines.append(
            f"| {bar}{mark} | {len(sent)} | {len(page_right)} | {precision:.3f} | "
            f"{page_precision:.3f} | {recall:.3f} | {', '.join(wrong) or '—'} |"
        )
    held = [
        r
        for r in ran
        if decide(router_at(0.0), r).branch is Branch.AUTO_REPLY
        and decide(router_at(current), r).branch is not Branch.AUTO_REPLY
    ]
    lines += [
        "",
        f"## Held back by the bar at {current}",
        "",
        "Tickets every other check would auto-reply: Jev's confidence, whether the case "
        "expects an auto-reply, and whether the cited page is right.",
        "",
        "| Case | Confidence | Expects | Cited page | Right page |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(held, key=lambda r: -r["signals"]["retrieval"]["rerank_confidence"]):
        lines.append(
            f"| {r['id']} | {r['signals']['retrieval']['rerank_confidence']:.2f} | "
            f"{r['truth']['expected_branch']} | {r['proposal']['kb_slug']} | "
            f"{'yes' if right_page(r) else 'no'} |"
        )
    if errors:
        lines += ["", f"Errors: {', '.join(sorted(errors))}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="run the golden set through ai-engine and save it")
    c.add_argument("--out", type=Path, default=None, help="resume into this file")
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--limit", type=int, default=None)
    s = sub.add_parser("sweep", help="replay the router over a collected run")
    s.add_argument("run", type=Path)
    s.add_argument("--bars", default=DEFAULT_BARS)
    args = parser.parse_args()
    if args.command == "collect":
        out = args.out or SWEEPS / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        collect(out, args.workers, args.limit)
    else:
        report = sweep(args.run, [float(b) for b in args.bars.split(",")])
        args.run.with_suffix(".md").write_text(report, encoding="utf-8")
        print(report)


if __name__ == "__main__":
    main()
