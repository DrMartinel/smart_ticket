"""
Plain helper functions for the eval suites — deliberately NOT in
conftest.py. conftest.py is auto-loaded by pytest as a plugin per
directory; it should only define fixtures, not double as an importable
library module (pytest fixture registration and a manual `import
conftest` in the same process is a common source of "why did this run
twice" bugs). Test files import from here instead:
`from suites.golden_utils import load_golden, sample, analyze`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

GOLDEN_PATH = Path(__file__).parent.parent / "golden" / "tickets.jsonl"
RESULTS_PATH = Path(__file__).parent.parent / ".results.json"  # gitignored — one run's output, read by report.py
AI_ENGINE_URL = os.environ.get("AI_ENGINE_URL", "http://localhost:8001")

# Live-pipeline suites call a real LLM per case (~3-5s each on local
# Ollama hardware). Running the full golden set on every local test
# invocation is impractical; CI / a real quality gate should set
# EVAL_FULL_RUN=1 to use the complete set (spec §12.3's actual gate).
# The default sample size is deliberately small — enough to prove the
# suite is wired correctly, not enough to trust the resulting numbers.
EVAL_FULL_RUN = os.environ.get("EVAL_FULL_RUN", "0") == "1"
DEFAULT_SAMPLE = int(os.environ.get("EVAL_SAMPLE_SIZE", "8"))


def load_golden(*tags: str) -> list[dict]:
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text().splitlines() if line.strip()]
    if not tags:
        return cases
    return [c for c in cases if any(t in c["tags"] for t in tags)]


def sample(cases: list[dict], n: int = DEFAULT_SAMPLE) -> list[dict]:
    return cases if EVAL_FULL_RUN else cases[:n]


def record_metric(name: str, value: float, **extra) -> None:
    """Appends one metric to .results.json for report.py to read. Each
    suite calls this with its headline number(s) — e.g.
    `record_metric("retrieval_recall_at_5", 0.92, n=60)`. Not a
    replacement for the suite's own assert; report.py's job is comparing
    THIS run's numbers against the committed baseline (spec §12.3), which
    needs them recorded somewhere a plain pytest exit code can't carry."""

    results = {}
    if RESULTS_PATH.exists():
        try:
            results = json.loads(RESULTS_PATH.read_text())
        except json.JSONDecodeError:
            results = {}
    results[name] = {"value": value, **extra}
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")


def analyze(client: httpx.Client, subject: str, body: str, *, retrieval_floor: float = 0.45) -> dict:
    from contracts.enums import PIILevel

    req = {
        "request_id": f"eval-{hash((subject, body)) & 0xFFFFFFFF}",
        "ticket": {
            "ticket_public_id": "TKT-EVAL",
            "subject_masked": subject,
            "body_masked": body,
            "pii_level": PIILevel.ROUTINE.value,
            "placeholder_keys": [],
        },
        "retrieval_floor": retrieval_floor,
        "max_tokens": 8000,
        "max_llm_calls": 4,
        "max_latency_sec": 60,
        "max_graph_iterations": 5,
    }
    resp = client.post("/v1/analyze", json=req)
    resp.raise_for_status()
    return resp.json()
