"""
Test settings, used by `pytest services/core-api` (see `pytest.ini`).

Tests never reach ai-engine: the autouse `_offline_ai_engine` fixture in
`conftest.py` answers `/v1/embed` with deterministic vectors and makes every
other call fail as unreachable. It is a fixture rather than a setting so
that whole-workspace runs, which use `development` settings (configured by
`evals/suites/conftest.py`), are covered too.
"""

from .base import *  # noqa: F403

# Fixtures create users with passwords; the default hasher is deliberately
# slow and tests do not exercise it.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
