"""Runs a simulated working day against the local stack: `uv run python -m tools.simulate`."""

from __future__ import annotations

import argparse
import os
import random
import time
from pathlib import Path

from .client import CallLog, Endpoints
from .day import Day, requests_for
from .idp import Directory
from .world import World

ROOT = Path(__file__).resolve().parents[2]


def dotenv(path: Path) -> dict[str, str]:
    """The root .env's values; real environment variables win."""
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return {**values, **{k: v for k, v in os.environ.items() if v}}


def report(world: World, out: Path, started: float) -> None:
    rows = world.log.rows
    lines = [
        f"# Simulated day, {time.strftime('%Y-%m-%d %H:%M', time.localtime(started))}",
        "",
        f"{len(rows)} API calls by {len({r['persona'] for r in rows})} people in {round((time.time() - started) / 60, 1)} min; "
        f"{sum(1 for r in rows if r['error'])} refused or failed.",
        "",
        "## Tickets",
        "",
        "| Request | Who | Channel | Ticket | Chat state | Branch | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in world.raised.values():
        if not r.key.startswith("_"):
            lines.append(
                f"| {r.key} | {r.who} | {r.channel} | {r.public_id} | {r.state or '—'} | {r.branch or '—'} | {r.reason or '—'} |"
            )
    lines += ["", "## Findings", ""]
    grouped: dict[tuple[str, str], list[str]] = {}
    for f in world.findings:
        grouped.setdefault((f.action, f.detail[:300]), []).append(f.persona)
    lines += [
        f"- {action} ×{len(who)} ({', '.join(sorted(set(who)))}): `{detail}`"
        for (action, detail), who in grouped.items()
    ] or ["None."]
    lines += ["", "## Actions", ""]
    lines += [f"- {what}: {n}" for what, n in sorted(world.counts.items())]
    lines += ["", "## Story", "", "```", *world.story, "```", ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=["smoke", "day"], default="day")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--think",
        type=float,
        default=1.0,
        help="seconds of think time between actions (0 for none)",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "tools" / "simulate" / "runs")
    args = parser.parse_args()

    env = dotenv(ROOT / ".env")
    ends = Endpoints(
        api=env.get("SIM_API_URL", "http://localhost:8000"),
        admin_origin=env.get("SIM_ADMIN_ORIGIN", "http://localhost:3000"),
        chat_origin=env.get("SIM_CHAT_ORIGIN", "http://localhost:3001"),
    )
    started = time.time()
    out = args.out / time.strftime("%Y%m%d-%H%M%S", time.localtime(started))
    out.mkdir(parents=True, exist_ok=True)
    world = World(ends, CallLog(str(out / "calls.jsonl")), random.Random(args.seed), args.think)
    directory = None
    if env.get("KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME") and env.get(
        "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD"
    ):
        directory = Directory(
            env.get("OIDC_SERVER_URL", "http://localhost:8081"),
            "smart-ticket",
            env["KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME"],
            env["KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD"],
        )
    try:
        Day(world, requests_for(args.scale), directory).run()
    finally:
        report(world, out, started)
        print(f"\nReport: {out / 'report.md'}")


if __name__ == "__main__":
    main()
