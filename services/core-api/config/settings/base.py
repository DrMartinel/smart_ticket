"""
Base Django settings. Environment-specific overrides live in development.py,
production.py and test.py.

Everything that varies between environments is read through `env()`: from
the repo root's `.env` (git-ignored; start from `cp .env.example .env`, the
template that documents each setting) or a real environment variable, which
wins. Never from a default in this file, and never from the template itself.
The template's values are dev-only: production.py refuses its secrets.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Environment ─────────────────────────────────────────────────────────
# The repo root (the image's /workspace). Containers have no .env there
# (.dockerignore): compose hands them its contents as environment variables.
REPO_ROOT = BASE_DIR.parent.parent
ENV_FILE = REPO_ROOT / ".env"


def layered_env(*sources: Mapping[str, str | None]) -> dict[str, str]:
    """Later sources win. Empty counts as unset: a blank line in .env is a
    setting nobody filled in, not a value."""
    return {key: value for source in sources for key, value in source.items() if value}


_ENV = layered_env(dotenv_values(ENV_FILE), os.environ)


def env(key: str) -> str:
    """A setting with no value anywhere fails the boot: there is no
    fallback to a number nobody chose."""
    try:
        return _ENV[key]
    except KeyError:
        raise ImproperlyConfigured(
            f"{key} is not set: add it to {ENV_FILE} (see .env.example) or the environment"
        )


def env_bool(key: str) -> bool:
    return env(key).lower() == "true"


def env_path(key: str) -> str:
    """Relative to the repo root, so it works from any cwd; an absolute
    path is kept as is."""
    return str((REPO_ROOT / env(key)).resolve())


SECRET_KEY = env("SECRET_KEY")
DEBUG = env_bool("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "ninja_extra",
    "apps.core",
    "apps.dbextras",
    "apps.accounts",
    "apps.audit",
    "apps.tickets",
    "apps.kb",
    "apps.review",
    "apps.fewshot",
    "apps.itsm_mock",
    "apps.metrics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.core.middleware.TraceIdMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES: list[dict[str, Any]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"

# ── Database ─────────────────────────────────────────────────────────────
# DATABASE_URL, e.g. postgresql://app_user:app_password@db:5432/smart_triage
_db_url = env("DATABASE_URL")


def _parse_database_url(url: str) -> dict[str, Any]:
    # Minimal parser to avoid an extra dependency (dj-database-url) for a
    # single, well-known URL shape.
    from urllib.parse import urlparse

    p = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": p.path.lstrip("/"),
        "USER": p.username,
        "PASSWORD": p.password,
        "HOST": p.hostname,
        "PORT": p.port or 5432,
    }


DATABASES = {"default": _parse_database_url(_db_url)}
# Only for Django's own auto-created tables (the user-to-group link table).
# Every model of ours declares a UUID primary key instead (ADR-0011), and
# apps/dbextras/tests/test_primary_keys.py fails if one forgets.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Celery ───────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_TASK_ACKS_LATE = True  # spec §10.3: worker death mid-task must not drop the ticket
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "expire-pii-quarantine": {
        "task": "apps.tickets.tasks.expire_pii_quarantine",
        "schedule": 3600.0,  # hourly
    },
    "expire-fewshot-examples": {
        "task": "apps.fewshot.tasks.expire_fewshot_examples",
        "schedule": 3600.0,
    },
    "weekly-drift-check": {
        "task": "apps.metrics.tasks.weekly_drift_check",
        "schedule": 604800.0,
    },
}

# ── CORS (web talks to core-api from a different origin in dev) ────────────
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS").split(",")

# ── Smart Triage domain settings ────────────────────────────────────────
SHADOW_MODE = env_bool("SHADOW_MODE")
# ai-engine is the only vLLM client (ADR-0012): core-api's embeddings and PII
# NER go through AI_ENGINE_URL, so core-api has no model URL, model name or
# embedding provider.
AI_ENGINE_URL = env("AI_ENGINE_URL")
# Read and connect timeouts for calls to ai-engine are separate on purpose;
# `.env.example` explains both values.
MODEL_TIMEOUT_SEC = float(env("MODEL_TIMEOUT_SEC"))
MODEL_CONNECT_TIMEOUT_SEC = float(env("MODEL_CONNECT_TIMEOUT_SEC"))
AI_ENGINE_ANALYZE_GRACE_SEC = float(env("AI_ENGINE_ANALYZE_GRACE_SEC"))
PII_ENCRYPTION_KEY = env("PII_ENCRYPTION_KEY")
PII_QUARANTINE_TTL_HOURS = int(env("PII_QUARANTINE_TTL_HOURS"))
AI_ENGINE_RO_PASSWORD = env("POSTGRES_AI_RO_PASSWORD")
DB_APP_ROLE = DATABASES["default"]["USER"]

# The schema of thresholds.yaml (spec §8, §13). Parsed at boot, so a missing
# or malformed file stops core-api starting instead of surfacing mid-routing.


class RoutingThresholds(BaseModel):
    t_auto: float = Field(ge=0, le=1)
    t_route: float = Field(ge=0, le=1)
    quote_match: float = Field(ge=0, le=1)


class RetrievalThresholds(BaseModel):
    # On Jev's scale, the final reranker on every run (ADR-0015).
    floor: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    bm25_top_k: int
    vector_top_k: int
    rrf_k: int
    rerank_top_n: int
    # No default on purpose: a thresholds file without it fails at boot
    # rather than scoring trust with a number nobody chose (hard rule 2).
    keyword_agreement_k: int = Field(ge=1)


class IncidentThresholds(BaseModel):
    similarity: float = Field(ge=0, le=1)
    window_minutes: int
    min_count: int
    sigma_multiplier: float


class FewshotThresholds(BaseModel):
    max_per_category: int
    ttl_days: int
    min_diversity: float
    require_user_confirmed: bool


class BudgetThresholds(BaseModel):
    max_latency_sec: int
    daily_cost_ceiling_usd: float


class AlertThresholds(BaseModel):
    reviewer_approve_rate_max: float
    reviewer_median_time_min_sec: int
    override_rate_delta_max: float
    trust_score_drift_max: float
    # No default, unlike new fields on other persisted schemas: Thresholds is
    # only ever parsed from thresholds.yaml at boot (the `thresholds_used`
    # snapshots are never read back into it), and a default here would be a
    # tunable living outside that file.
    trust_score_std_min: float


class MaskingThresholds(BaseModel):
    # Above this share of a ticket's text, NER's spans (beyond the regex
    # hits) make the ticket MASK_FAILED instead of passing it on over-masked.
    ner_max_share: float = Field(gt=0, le=1)


class Thresholds(BaseModel):
    """Loaded from config/thresholds.yaml. Passed as a parameter everywhere
    it's used — never imported as a global — so it can be varied in tests
    and snapshotted verbatim into `routing_decisions.thresholds_used`."""

    version: str
    calibration_source: str
    routing: RoutingThresholds
    retrieval: RetrievalThresholds
    incident: IncidentThresholds
    fewshot: FewshotThresholds
    budget: BudgetThresholds
    alerts: AlertThresholds
    masking: MaskingThresholds

    @property
    def retrieval_floor(self) -> float:
        return self.retrieval.floor

    @property
    def t_auto(self) -> float:
        return self.routing.t_auto

    @property
    def t_route(self) -> float:
        return self.routing.t_route

    @property
    def quote_match(self) -> float:
        return self.routing.quote_match


THRESHOLDS_PATH = env_path("THRESHOLDS_PATH")

# The demo knowledge base snapshot (repo-root demo_kb/), read by
# `manage.py load_demo_kb`. docker-compose mounts it at the same place.
DEMO_KB_DIR = env_path("DEMO_KB_DIR")


def load_thresholds() -> Thresholds:
    # encoding is explicit: without it Python uses the locale default, which is
    # cp1252 on Windows, and thresholds.yaml carries non-ASCII (the 🔧 markers on
    # unfitted values, ⚠️ on the calibration warnings). Those used to decode into
    # silent mojibake — cp1252 happens to map every byte of 🔧 — until a
    # character containing 0x8f made it throw, taking core-api's boot with it.
    # Same defect as the golden-set loader fixed in evals/suites/golden_utils.py.
    with open(THRESHOLDS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Thresholds(**data)


THRESHOLDS = load_thresholds()

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL")},
}
