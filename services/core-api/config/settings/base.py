"""
Base Django settings. Environment-specific overrides live in development.py,
production.py and test.py.

Everything that varies between environments is read from os.environ here,
with dev-safe defaults — those defaults are NOT meant to be used in prod
(see production.py, which fails loudly if left unset).
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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
_db_url = os.environ.get(
    "DATABASE_URL", "postgresql://app_user:app_password@localhost:5432/smart_triage"
)


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
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
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
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# ── Smart Triage domain settings ────────────────────────────────────────
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"
AI_ENGINE_URL = os.environ.get("AI_ENGINE_URL", "http://localhost:8001")
# ai-engine is the only vLLM client (ADR-0012): core-api's embeddings and PII
# NER go through AI_ENGINE_URL, so core-api has no model URL, model name or
# embedding provider. EMBEDDING_PROVIDER=stub is set on ai-engine.
#
# Read timeout for one embed or PII NER call to ai-engine, which in turn
# waits on a model. Generous by design:
# a cold model load alone can take 15-20s, and the old 3s NER budget
# meant essentially every ticket timed out into PIILevel.MASK_FAILED before
# the model had even finished loading. Failing to MASK_FAILED is the
# correct behavior when we genuinely can't verify (spec §5.2) — but it
# should signal "the model is down", not "the model was still warming up".
MODEL_TIMEOUT_SEC = float(os.environ.get("MODEL_TIMEOUT_SEC", "120"))
# Connect timeout for every call to ai-engine, deliberately SHORT and
# separate from the read budgets. The two describe different failures:
#   - can't open a TCP connection  -> ai-engine unreachable (down, wrong
#     host, firewall dropping the Docker subnet). Waiting longer cannot
#     help; a dropped packet just burns the full budget in silence.
#   - connected but slow to respond -> a model is loading or generating.
#     That legitimately needs the full read budget.
# Collapsing both into one number means an unreachable server makes the
# user stare at a spinner for two minutes before an error that was
# knowable in three seconds — masking runs inline in the submit request,
# so this delay is felt directly by whoever filed the ticket.
MODEL_CONNECT_TIMEOUT_SEC = float(os.environ.get("MODEL_CONNECT_TIMEOUT_SEC", "3"))
# Slack on top of thresholds.yaml's budget.max_latency_sec for the
# /v1/analyze read timeout, so a run that finishes right at the budget
# still delivers its response.
AI_ENGINE_ANALYZE_GRACE_SEC = float(os.environ.get("AI_ENGINE_ANALYZE_GRACE_SEC", "5"))
PII_ENCRYPTION_KEY = os.environ.get(
    "PII_ENCRYPTION_KEY", "Zm9yLWRldi1vbmx5LTMyLWJ5dGUta2V5LWhlcmUhISE="
)
PII_QUARANTINE_TTL_HOURS = int(os.environ.get("PII_QUARANTINE_TTL_HOURS", "72"))
AI_ENGINE_RO_PASSWORD = os.environ.get("POSTGRES_AI_RO_PASSWORD", "ai_engine_ro_password")
DB_APP_ROLE = DATABASES["default"]["USER"]

# The schema of thresholds.yaml (spec §8, §13). Parsed at boot, so a missing
# or malformed file stops core-api starting instead of surfacing mid-routing.


class RoutingThresholds(BaseModel):
    t_auto: float = Field(ge=0, le=1)
    t_route: float = Field(ge=0, le=1)
    quote_match: float = Field(ge=0, le=1)


class RetrievalThresholds(BaseModel):
    floor: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    bm25_top_k: int
    vector_top_k: int
    rrf_k: int
    rerank_top_n: int


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


THRESHOLDS_PATH = os.environ.get("THRESHOLDS_PATH", str(BASE_DIR / "config" / "thresholds.yaml"))


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
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
