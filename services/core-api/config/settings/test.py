"""
Test settings, used by `pytest services/core-api` (see `pytest.ini`).

Tests must never reach a model server, so the embedder is the deterministic
stub whatever the environment says; CI already sets it, and this makes a
local run match. A test of the vLLM path sets EMBEDDING_PROVIDER itself
(`infrastructure/tests/test_embeddings.py`).

Whole-workspace runs (`uv run pytest` from the repo root) are configured by
`evals/suites/conftest.py` instead, with `development`: the live eval suites
need the real embedder when the environment asks for it.
"""

from .base import *  # noqa: F403

EMBEDDING_PROVIDER = "stub"  # pyright: ignore[reportConstantRedefinition]

# Fixtures create users with passwords; the default hasher is deliberately
# slow and tests do not exercise it.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
