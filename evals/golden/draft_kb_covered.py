#!/usr/bin/env python3
"""
Drafts `kb_covered` tickets for the golden set with DeepSeek (ADR-0019: KB
text only, never a ticket), one per sampled demo-KB page. A draft is not a
golden ticket: each is reviewed (paraphrase, answerable by the page, one
right page, realistic) before `kb_covered_drafted.jsonl` takes it, and
`generate_golden.py` builds tickets from that file only.

    uv run --package evals python evals/golden/draft_kb_covered.py sample --count 440 --out DIR
    uv run --package evals python evals/golden/draft_kb_covered.py draft --dir DIR
    uv run --package evals python evals/golden/draft_kb_covered.py redraft --dir DIR --verdicts FILE

`sample` picks pages stratified by guide, in proportion to each guide's size,
with a fixed seed; duplicate-text copies and pages already a golden target
are never picked. `draft` writes `drafts.jsonl` (resumable: a page drafted
already is skipped); a page the model judges no ticket would be about is
marked `skip` and replaced by `sample --extend`. `redraft` rewrites each
rejected draft once, given the reviewer's reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

ROOT = Path(__file__).resolve().parents[2]
DEMO_KB = ROOT / "demo_kb"
GOLDEN = Path(__file__).parent / "tickets.jsonl"
SEED = 0
MAX_PAGE_CHARS = 24_000
CONCURRENCY = 16

# Versioned with the file: change the text, change the version.
PROMPT_VERSION = "draft_kb_covered.v1"
PROMPT = """\
You write realistic IT support tickets for an evaluation set. The help desk
serves employees of a company that runs on AWS.

You are given one documentation page. Write ONE ticket from an employee who
has the problem this page solves, or needs to do what this page explains,
without having read the page:

- Describe what they see, what they tried, or what they need, in their own
  everyday words: symptoms, error text they would plausibly see, context.
- Do NOT reuse the page's title, headings or distinctive phrases, and do not
  name the documentation. Do not explain the solution.
- 1 to 4 sentences of body, a short subject. English. No real names, emails
  or phone numbers.
- The ticket must be one this page (and not merely its general topic)
  would resolve.

If no employee would plausibly file a ticket this page resolves (a pure
reference table, a pricing page, a list of API names, a glossary), set
"skip" to true.

Reply with one JSON object:
{"skip": false, "subject": "...", "body": "..."}"""

REDRAFT = """\
A reviewer rejected your ticket for this page. Reason: {reason}

Your ticket was:
Subject: {subject}
Body: {body}

Write a new ticket that fixes the problem the reviewer named, following the
same rules. Reply with one JSON object: {{"skip": false, "subject": "...", "body": "..."}}"""

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def pages() -> list[dict]:
    return json.loads((DEMO_KB / "manifest.json").read_text(encoding="utf-8"))["pages"]


def page_text(page: dict) -> str:
    text = (DEMO_KB / page["path"]).read_text(encoding="utf-8")
    return _LINK.sub(r"\1", text)[:MAX_PAGE_CHARS]


def eligible(all_pages: list[dict]) -> list[dict]:
    """Pages a new ticket may target: not a duplicate-text copy (the same
    page under two URLs, whose ticket would have two right pages) and not
    already a golden target."""

    taken = {
        json.loads(line)["truth"].get("kb_slug")
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    drafted = Path(__file__).parent / "kb_covered_drafted.jsonl"
    if drafted.exists():
        taken |= {json.loads(line)["slug"] for line in drafted.read_text().splitlines() if line}
    by_text: dict[str, str] = {}
    copies = set()
    for p in sorted(all_pages, key=lambda p: p["slug"]):
        if p["sha256"] in by_text:
            copies.add(p["slug"])
        else:
            by_text[p["sha256"]] = p["slug"]
    return [p for p in all_pages if p["slug"] not in taken and p["slug"] not in copies]


def allocate(total: int, sizes: dict[str, int]) -> dict[str, int]:
    """`total` split across guides in proportion to `sizes`, largest
    remainders first, so the parts add up exactly."""

    whole = sum(sizes.values())
    exact = {g: total * n / whole for g, n in sizes.items()}
    out = {g: int(x) for g, x in exact.items()}
    for g in sorted(exact, key=lambda g: exact[g] - out[g], reverse=True)[
        : total - sum(out.values())
    ]:
        out[g] += 1
    return out


def cmd_sample(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "sample.jsonl"
    chosen = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    have = {c["slug"] for c in chosen}
    pool = [p for p in eligible(pages()) if p["slug"] not in have]
    by_guide: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(pool, key=lambda p: p["slug"]):
        by_guide[p["guide"]].append(p)
    rng = random.Random(SEED + len(chosen))
    if args.extend:
        # Replace skipped and dropped pages within their own guide.
        need = Counter(
            json.loads(line)["guide"] for line in Path(args.extend).read_text().splitlines() if line
        )
    else:
        need = Counter(allocate(args.count, Counter(p["guide"] for p in pages())))
    added = []
    for guide, n in sorted(need.items()):
        added += rng.sample(by_guide[guide], min(n, len(by_guide[guide])))
    with path.open("a", encoding="utf-8") as f:
        for p in added:
            f.write(
                json.dumps({k: p[k] for k in ("slug", "guide", "title", "path", "category")}) + "\n"
            )
    print(f"{len(added)} pages added, {len(chosen) + len(added)} in {path}")
    return 0


async def _ask(model, messages) -> dict:
    reply = await model.ainvoke(messages)
    data = json.loads(reply.content)
    if data.get("skip") is True:
        return {"skip": True}
    subject, body = str(data.get("subject", "")).strip(), str(data.get("body", "")).strip()
    if not subject or not body:
        raise ValueError("empty subject or body")
    return {"skip": False, "subject": subject, "body": body}


async def _run(jobs, model) -> list[dict]:
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(job):
        async with limit:
            try:
                return {**job["row"], **(await _ask(model, job["messages"]))}
            except Exception as e:  # noqa: BLE001 - reported; the page is re-drafted next run
                return {**job["row"], "error": f"{type(e).__name__}: {e}"[:200]}

    return await asyncio.gather(*(one(j) for j in jobs))


def _model():
    from ai_engine.core.providers.clients import deepseek_model

    return deepseek_model(json_mode=True, temperature=0.7)


def cmd_draft(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    sample = [json.loads(line) for line in (d / "sample.jsonl").read_text().splitlines()]
    out = d / "drafts.jsonl"
    done = (
        {json.loads(line)["slug"] for line in out.read_text().splitlines()}
        if out.exists()
        else set()
    )
    jobs = [
        {
            "row": {**p, "attempt": 1, "prompt": PROMPT_VERSION},
            "messages": [
                SystemMessage(content=PROMPT),
                HumanMessage(content=f"Page title: {p['title']}\n\n{page_text(p)}"),
            ],
        }
        for p in sample
        if p["slug"] not in done
    ]
    rows = asyncio.run(_run(jobs, _model()))
    good = [r for r in rows if "error" not in r]
    with out.open("a", encoding="utf-8") as f:
        for r in good:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(
        f"{len(good)} drafted ({sum(r['skip'] for r in good)} skipped as no-ticket pages), "
        f"{len(rows) - len(good)} failed (re-run to retry)"
    )
    return 0 if len(good) == len(rows) else 1


def cmd_redraft(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    drafts = {
        json.loads(line)["slug"]: json.loads(line)
        for line in (d / "drafts.jsonl").read_text().splitlines()
    }
    verdicts = [json.loads(line) for line in Path(args.verdicts).read_text().splitlines() if line]
    out = d / "redrafts.jsonl"
    done = (
        {json.loads(line)["slug"] for line in out.read_text().splitlines()}
        if out.exists()
        else set()
    )
    jobs = []
    for v in verdicts:
        if v["verdict"] != "reject" or v["slug"] in done:
            continue
        p = drafts[v["slug"]]
        jobs.append(
            {
                "row": {k: p[k] for k in ("slug", "guide", "title", "path", "category")}
                | {"attempt": 2, "prompt": PROMPT_VERSION},
                "messages": [
                    SystemMessage(content=PROMPT),
                    HumanMessage(content=f"Page title: {p['title']}\n\n{page_text(p)}"),
                    HumanMessage(
                        content=REDRAFT.format(
                            reason=v["reason"], subject=p["subject"], body=p["body"]
                        )
                    ),
                ],
            }
        )
    rows = asyncio.run(_run(jobs, _model()))
    good = [r for r in rows if "error" not in r]
    with out.open("a", encoding="utf-8") as f:
        for r in good:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(good)} redrafted, {len(rows) - len(good)} failed (re-run to retry)")
    return 0 if len(good) == len(rows) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--count", type=int, default=440)
    s.add_argument("--out", required=True)
    s.add_argument("--extend", help="a JSONL of rows whose guides need replacement pages")
    dr = sub.add_parser("draft")
    dr.add_argument("--dir", required=True)
    rd = sub.add_parser("redraft")
    rd.add_argument("--dir", required=True)
    rd.add_argument("--verdicts", required=True)
    args = parser.parse_args(argv)
    return {"sample": cmd_sample, "draft": cmd_draft, "redraft": cmd_redraft}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
