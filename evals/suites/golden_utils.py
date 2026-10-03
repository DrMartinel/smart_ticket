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

import functools
import json
import os

from pathlib import Path

import httpx

GOLDEN_PATH = Path(__file__).parent.parent / "golden" / "tickets.jsonl"
# The demo KB snapshot's manifest: slug -> proposed category, for resolving
# the category of an auto_reply proposal. Read by the eval, never by the
# system under test.
DEMO_KB_MANIFEST = Path(__file__).parent.parent.parent / "demo_kb" / "manifest.json"
RESULTS_PATH = (
    Path(__file__).parent.parent / ".results.json"
)  # gitignored — one run's output, read by report.py
AI_ENGINE_URL = os.environ.get("AI_ENGINE_URL", "http://localhost:8001")

# Live-pipeline suites call a real LLM per case (~3-5s each on local
# vLLM hardware). Running the full golden set on every local test
# invocation is impractical; CI / a real quality gate should set
# EVAL_FULL_RUN=1 to use the complete set (spec §12.3's actual gate).
# The default sample size is deliberately small — enough to prove the
# suite is wired correctly, not enough to trust the resulting numbers.
EVAL_FULL_RUN = os.environ.get("EVAL_FULL_RUN", "0") == "1"
DEFAULT_SAMPLE = int(os.environ.get("EVAL_SAMPLE_SIZE", "8"))


def load_golden(*tags: str) -> list[dict]:
    cases = [
        json.loads(line)
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not tags:
        return cases
    return [c for c in cases if any(t in c["tags"] for t in tags)]


@functools.cache
def _kb_categories() -> dict[str, str]:
    pages = json.loads(DEMO_KB_MANIFEST.read_text(encoding="utf-8"))["pages"]
    return {p["slug"]: p["category"] for p in pages}


def kb_category(slug: str) -> str | None:
    return _kb_categories().get(slug)


def sample(cases: list[dict], n: int = DEFAULT_SAMPLE) -> list[dict]:
    return cases if EVAL_FULL_RUN else cases[:n]


def record_metric(name: str, value: float, **extra) -> None:
    """Appends one metric to .results.json for report.py to read. Each
    suite calls this with its headline number(s) — e.g.
    `record_metric("retrieval_recall_at_3", 0.92, n=60)`. Not a
    replacement for the suite's own assert; report.py's job is comparing
    THIS run's numbers against the committed baseline (spec §12.3), which
    needs them recorded somewhere a plain pytest exit code can't carry."""

    results = {}
    if RESULTS_PATH.exists():
        try:
            results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = {}
    results[name] = {"value": value, **extra}
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")


def analyze(client: httpx.Client, subject: str, body: str, *, never_refuse: bool = False) -> dict:
    """POST /v1/analyze with thresholds.yaml's floor, or 0.0 when
    `never_refuse`, so the model always answers.

    The ticket goes through core-api's own `mask()` first and ai-engine gets
    what `pipeline.py` sends it: the masked text and the PII level masking
    found. ai-engine echoes that level into its policy signals, so the
    router blocks critical PII and sends `mask_failed` to a human, as in
    production. Before, the harness sent raw text as "masked" with the level
    pinned to routine: g144's raw password was auto-replied in the
    2026-10-04 run instead of blocked, and no masking regression could show
    up here. Masking calls ai-engine's NER, so a run needs it up."""

    from asgiref.sync import async_to_sync
    from django.conf import settings

    from apps.tickets.request_schema import TicketIn
    from apps.tickets.utils.masking import mask

    floor = 0.0 if never_refuse else settings.THRESHOLDS.retrieval_floor
    masked = async_to_sync(mask)(
        TicketIn(subject=subject, body=body), settings.THRESHOLDS.masking.ner_max_share
    )

    req = {
        "request_id": f"eval-{hash((subject, body)) & 0xFFFFFFFF}",
        "ticket": {
            "ticket_public_id": "TKT-EVAL",
            "subject_masked": masked.subject_masked,
            "body_masked": masked.body_masked,
            "pii_level": masked.pii_level.value,
            "placeholder_keys": list(masked.placeholder_map),
        },
        "retrieval_floor": floor,
    }
    resp = client.post("/v1/analyze", json=req)
    resp.raise_for_status()
    return resp.json()
