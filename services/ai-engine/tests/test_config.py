"""
Settings come from the repo root's `.env` or the environment, never from a
default in `config.py` and never from the `.env.example` template. A default
in code would be a second copy that drifts silently: change `.env`, and the
code keeps running the old number wherever the variable isn't set. The
template's job is to be complete, so a copied `.env` boots.
"""

from __future__ import annotations

import pytest

from pydantic import ValidationError

from ai_engine.core.config import Settings

# Optional secrets and proxy: `None` means "not configured", not a value.
_UNSET_ALLOWED = {"cloud_api_key", "cloud_base_url", "cloud_model", "jev_api_key"}


def _env_name(name: str) -> str:
    alias = Settings.model_fields[name].validation_alias
    return alias if isinstance(alias, str) else name.upper()


def _write_env(tmp_path, values: dict[str, str]):
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return path


@pytest.fixture
def no_env_vars(monkeypatch):
    """Clear every setting from the process env, so only the file under
    test supplies values (CI exports some)."""
    for name in Settings.model_fields:
        monkeypatch.delenv(_env_name(name), raising=False)


def test_no_setting_has_a_default_in_code():
    """Every value comes from .env or the env; the only defaults are the
    `None` of an optional secret."""

    defaulted = {
        name: field.default
        for name, field in Settings.model_fields.items()
        if not field.is_required()
    }

    assert set(defaulted) == _UNSET_ALLOWED
    assert all(v is None for v in defaulted.values())


def test_the_template_lists_every_setting(env_template):
    """`.env` starts as a copy of `.env.example`. A setting missing from the
    template fails every fresh checkout's boot. (Keys there that nothing
    reads are caught by core-api's test_settings_env, which sees every
    reader.)"""

    names = {_env_name(name) for name in Settings.model_fields}

    assert names <= set(env_template)


def test_a_copy_of_the_template_boots(env_template, no_env_vars, tmp_path):
    """`cp .env.example .env` is the documented setup; it must produce
    settings that validate, with nothing else set."""

    env = _write_env(tmp_path, {k: v or "" for k, v in env_template.items()})

    Settings(_env_file=env)  # type: ignore[call-arg]  # the values are in the file


def test_the_template_is_never_read_as_defaults(env_template, no_env_vars, tmp_path):
    """With an empty `.env` and no env vars, nothing fills the gaps: not a
    code default, not the template beside it."""

    with pytest.raises(ValidationError, match="AI_ENGINE_DATABASE_URL"):
        Settings(_env_file=_write_env(tmp_path, {}))  # type: ignore[call-arg]


def test_the_read_only_dsn_is_never_core_apis(env_template, no_env_vars, tmp_path, monkeypatch):
    """ADR-0004: ai-engine connects as the SELECT-only role. Both DSNs share
    one `.env`, so ai-engine must read only AI_ENGINE_DATABASE_URL: falling
    back to DATABASE_URL would hand it core-api's read-write role with
    nothing looking wrong."""

    values = {k: v or "" for k, v in env_template.items() if k != "AI_ENGINE_DATABASE_URL"}
    monkeypatch.setenv("DATABASE_URL", "postgresql://app_user:pw@db/x")

    with pytest.raises(ValidationError, match="AI_ENGINE_DATABASE_URL"):
        Settings(_env_file=_write_env(tmp_path, values))  # type: ignore[call-arg]
