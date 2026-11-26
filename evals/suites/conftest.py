"""
Shared eval-suite fixtures.

Django is configured (settings only — no DB connection is opened unless a
test actually queries the DB) so suites can call core-api's `router.route`
and `trust_scorer.score` directly, as pure functions, without needing a
running core-api HTTP server. ai-engine's pure nodes (injection detector,
validator, RRF fusion) are imported the same way. Anything that needs
real retrieval/LLM output goes over HTTP to a live ai-engine instance at
AI_ENGINE_URL and is skipped — not failed — when that's unreachable, so
`pytest evals/suites` stays runnable in environments without vLLM. The agent
trace suite is the exception: it needs Postgres through pytest-django.
"""

from __future__ import annotations

import os

import django
import httpx
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
os.environ.setdefault("EMBEDDING_PROVIDER", "stub")
django.setup()

from apps.tickets.domain.router import CategorySet  # noqa: E402
from suites.golden_utils import AI_ENGINE_URL, load_golden, record_metric  # noqa: E402


@pytest.fixture(scope="session")
def golden_cases() -> list[dict]:
    return load_golden()


@pytest.fixture(scope="session")
def categories(django_db_blocker) -> CategorySet:
    """The category set the pipeline would send, read once from the dev database and recorded
    with the run's results (ADR-0049)."""
    from apps.tickets.services.pipeline import category_set

    with django_db_blocker.unblock():
        found = category_set()
    record_metric("category_set", float(len(found.categories)), categories=found.as_used())
    return found


@pytest.fixture(scope="session")
def ai_engine_client():
    """Skips the whole test (not a failure) if ai-engine isn't reachable —
    these suites measure MODEL/PIPELINE quality, not code correctness, so
    "can't reach the pipeline" is a different failure mode than "the
    pipeline gave a wrong answer" and shouldn't be reported as the latter."""

    try:
        resp = httpx.get(f"{AI_ENGINE_URL}/healthz", timeout=3.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"ai-engine not reachable at {AI_ENGINE_URL} — skipping live-pipeline eval")

    client = httpx.Client(base_url=AI_ENGINE_URL, timeout=120.0)
    yield client
    client.close()
