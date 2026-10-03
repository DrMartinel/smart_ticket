"""
Settings come from the repo root's `.env` or the environment, never from a
default in the settings code and never from the `.env.example` template. A
default in code would be a second copy that drifts silently. The template's
job is to be complete and to hold nothing dead, so a copied `.env` boots and
every key in it does something.
"""

from __future__ import annotations

import importlib
import re
import sys

import pytest
import yaml

from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values

from config.settings import base

_TEMPLATE = dotenv_values(base.REPO_ROOT / ".env.example")

# env("X"), env_bool("X"), env_path("X"), and production's checked secrets.
_ENV_CALL = re.compile(r'env(?:_bool|_path)?\("([A-Z0-9_]+)"\)')
_PRODUCTION_CHECKED = {"SECRET_KEY", "PII_ENCRYPTION_KEY"}


def _read_by_core_api() -> set[str]:
    return set(_ENV_CALL.findall(open(base.__file__, encoding="utf-8").read()))


def _read_by_ai_engine() -> set[str]:
    """ai-engine's Settings fields, by text: no cross-service import
    (ADR-0010). A field's env name is its alias, else its name uppercased."""
    source = (base.REPO_ROOT / "services/ai-engine/src/ai_engine/core/config.py").read_text()
    body = source.split("class Settings", 1)[1]
    names = {n.upper() for n in re.findall(r"^    ([a-z_0-9]+): ", body, re.MULTILINE)}
    aliases = re.findall(r'validation_alias="([A-Z_0-9]+)"', body)
    aliased = re.findall(r"^    ([a-z_0-9]+): .*validation_alias=", body, re.MULTILINE)
    return (names - {n.upper() for n in aliased}) | set(aliases)


def _read_by_compose() -> set[str]:
    return set(re.findall(r"\$\{([A-Z_0-9]+)", (base.REPO_ROOT / "docker-compose.yml").read_text()))


def test_the_template_lists_every_key_core_api_reads():
    assert _read_by_core_api() <= set(_TEMPLATE)
    assert _PRODUCTION_CHECKED <= _read_by_core_api()


def test_every_template_key_has_a_reader():
    """One `.env` serves core-api, ai-engine and compose. A key none of them
    reads is a typo or a leftover, and would look configured."""

    readers = _read_by_core_api() | _read_by_ai_engine() | _read_by_compose()

    assert set(_TEMPLATE) - readers == set()


def test_a_key_with_no_value_anywhere_fails_the_boot(monkeypatch):
    """No fallback to a value nobody chose."""

    monkeypatch.setattr(base, "_ENV", {})

    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        base.env("DATABASE_URL")


def test_the_environment_wins_and_empty_counts_as_unset():
    """A real env var overrides `.env`. A blank one is a setting nobody
    filled in: if "" won, MODEL_TIMEOUT_SEC would fail to parse and
    SECRET_KEY would be empty instead of the `.env` value."""

    layered = base.layered_env({"A": "file", "B": "file"}, {"A": "process", "B": ""})

    assert layered == {"A": "process", "B": "file"}


def test_productions_denylist_is_the_templates_dev_secrets():
    """production.py refuses the template's public dev secrets by value. If
    the template's dev value changed and the denylist didn't, production
    would accept the new public value."""

    from config.settings.production import DEV_ONLY_SECRETS

    assert set(DEV_ONLY_SECRETS) == _PRODUCTION_CHECKED
    assert DEV_ONLY_SECRETS == {k: _TEMPLATE[k] for k in _PRODUCTION_CHECKED}


@pytest.mark.parametrize("key", sorted(_PRODUCTION_CHECKED))
def test_production_refuses_a_dev_secret(monkeypatch, key):
    """The template's secrets are public: a `.env` copied for production
    without replacing them must not boot."""

    real = {k: f"real-{k}" for k in _PRODUCTION_CHECKED}
    monkeypatch.setattr(base, "_ENV", {**base._ENV, **real, key: _TEMPLATE[key]})
    monkeypatch.delitem(sys.modules, "config.settings.production", raising=False)

    with pytest.raises(RuntimeError, match=key):
        importlib.import_module("config.settings.production")


def test_production_accepts_real_secrets(monkeypatch):
    real = {k: f"real-{k}" for k in _PRODUCTION_CHECKED}
    monkeypatch.setattr(base, "_ENV", {**base._ENV, **real})
    monkeypatch.delitem(sys.modules, "config.settings.production", raising=False)

    importlib.import_module("config.settings.production")


def _compose_env(service: str) -> set[str]:
    compose = yaml.safe_load((base.REPO_ROOT / "docker-compose.yml").read_text())
    return set(compose["services"][service]["environment"])


# Set by compose for the container, not settings any service reads.
_COMPOSE_ONLY = {"DJANGO_SETTINGS_MODULE", "REDIS_URL"}


@pytest.mark.parametrize("service", ["core-api", "worker", "beat"])
def test_compose_gives_core_api_exactly_what_it_reads(service):
    """A setting missing from the container's allowlist fails its boot; an
    extra one is another service's value it has no business holding."""

    assert _compose_env(service) - _COMPOSE_ONLY == _read_by_core_api()


def test_compose_gives_ai_engine_exactly_what_it_reads():
    """ADR-0004 in the container: ai-engine's environment is its own
    settings only, so core-api's read-write DSN and Django secret are never
    in reach of the service the boundary exists to contain."""

    env = _compose_env("ai-engine")

    assert env == _read_by_ai_engine()
    assert env.isdisjoint(
        {"DATABASE_URL", "POSTGRES_APP_PASSWORD", "SECRET_KEY", "PII_ENCRYPTION_KEY"}
    )
