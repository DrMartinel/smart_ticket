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
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from corsheaders.defaults import default_headers as default_cors_headers
from django.core.exceptions import ImproperlyConfigured
from celery.schedules import crontab
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
    "apps.chat",
    "apps.lifecycle",
    "apps.teams",
    "apps.notifications",
    "apps.sla",
    "apps.requester",
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
    "lifecycle-watchdog": {
        "task": "apps.lifecycle.tasks.watchdog",
        "schedule": float(env("LIFECYCLE_WATCHDOG_INTERVAL_SEC")),
    },
    "notifications-sweep": {
        "task": "apps.notifications.tasks.sweep",
        "schedule": float(env("NOTIFICATION_SWEEP_INTERVAL_SEC")),
    },
    "sla-sweep": {
        "task": "apps.sla.tasks.sweep",
        "schedule": float(env("SLA_SWEEP_INTERVAL_SEC")),
    },
    "requester-sweep": {
        "task": "apps.requester.tasks.sweep",
        "schedule": float(env("REQUESTER_SWEEP_INTERVAL_SEC")),
    },
    "sla-holiday-check": {
        "task": "apps.sla.tasks.holiday_check",
        # 07:00 Asia/Ho_Chi_Minh (UTC+7); CELERY_TIMEZONE is UTC.
        "schedule": crontab(minute=0, hour=0),
    },
    "notifications-purge": {
        "task": "apps.notifications.tasks.purge",
        # 02:00 Asia/Ho_Chi_Minh (UTC+7); CELERY_TIMEZONE is UTC.
        "schedule": crontab(minute=0, hour=19),
    },
}

# ── CORS (web talks to core-api from a different origin in dev) ────────────
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS").split(",")
# The refresh cookie travels on the frontends' credentialed requests (ADR-0029).
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_cors_headers, "x-auth-client")

# ── Sign-in sessions (ADR-0029); `.env.example` explains each value ──────
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(seconds=int(env("AUTH_ACCESS_TOKEN_LIFETIME_SEC"))),
}
AUTH_REFRESH_IDLE_HOURS = int(env("AUTH_REFRESH_IDLE_HOURS"))
AUTH_SESSION_MAX_HOURS = int(env("AUTH_SESSION_MAX_HOURS"))
AUTH_REFRESH_REUSE_GRACE_SEC = int(env("AUTH_REFRESH_REUSE_GRACE_SEC"))
AUTH_COOKIE_SECURE = env_bool("AUTH_COOKIE_SECURE")
AUTH_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE")
if AUTH_COOKIE_SAMESITE not in ("Lax", "Strict", "None"):
    raise ImproperlyConfigured("AUTH_COOKIE_SAMESITE must be Lax, Strict or None")

# ── Sign-in through Keycloak (F13, ADR-0032); `.env.example` explains each value ──
OIDC_ISSUER_URL = env("OIDC_ISSUER_URL")
OIDC_SERVER_URL = env("OIDC_SERVER_URL")
OIDC_CLIENT_ID = env("OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET = env("OIDC_CLIENT_SECRET")
OIDC_REDIRECT_URIS = env("OIDC_REDIRECT_URIS").split(",")
OIDC_JWKS_CACHE_SEC = int(env("OIDC_JWKS_CACHE_SEC"))
OIDC_MIN_REFETCH_SEC = float(env("OIDC_MIN_REFETCH_SEC"))
OIDC_CLOCK_SKEW_SEC = int(env("OIDC_CLOCK_SKEW_SEC"))
OIDC_HTTP_CONNECT_TIMEOUT_SEC = float(env("OIDC_HTTP_CONNECT_TIMEOUT_SEC"))
OIDC_HTTP_READ_TIMEOUT_SEC = float(env("OIDC_HTTP_READ_TIMEOUT_SEC"))
KEYCLOAK_ADMIN_CLIENT_ID = env("KEYCLOAK_ADMIN_CLIENT_ID")
KEYCLOAK_ADMIN_CLIENT_SECRET = env("KEYCLOAK_ADMIN_CLIENT_SECRET")

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

# ── Ticket lifecycle (ADR-0028); `.env.example` explains each value ──────
LIFECYCLE_HTTP_CONNECT_TIMEOUT_SEC = float(env("LIFECYCLE_HTTP_CONNECT_TIMEOUT_SEC"))
LIFECYCLE_HTTP_READ_TIMEOUT_SEC = float(env("LIFECYCLE_HTTP_READ_TIMEOUT_SEC"))
LIFECYCLE_HTTP_TOTAL_TIMEOUT_SEC = float(env("LIFECYCLE_HTTP_TOTAL_TIMEOUT_SEC"))
LIFECYCLE_RULE_PATTERN_TIMEOUT_SEC = float(env("LIFECYCLE_RULE_PATTERN_TIMEOUT_SEC"))
LIFECYCLE_HTTP_MAX_RESPONSE_BYTES = int(env("LIFECYCLE_HTTP_MAX_RESPONSE_BYTES"))
LIFECYCLE_WEBHOOK_ALLOWED_HOSTS = [
    h.strip().lower() for h in env("LIFECYCLE_WEBHOOK_ALLOWED_HOSTS").split(",") if h.strip()
]
LIFECYCLE_PUBLIC_BASE_URL = env("LIFECYCLE_PUBLIC_BASE_URL")
LIFECYCLE_CALLBACK_WAIT_SEC = int(env("LIFECYCLE_CALLBACK_WAIT_SEC"))
LIFECYCLE_RUN_STUCK_SEC = int(env("LIFECYCLE_RUN_STUCK_SEC"))
LIFECYCLE_RETRY_BACKOFF_BASE_SEC = float(env("LIFECYCLE_RETRY_BACKOFF_BASE_SEC"))
LIFECYCLE_RETRY_BACKOFF_MAX_SEC = float(env("LIFECYCLE_RETRY_BACKOFF_MAX_SEC"))

EMAIL_BACKEND = env("EMAIL_BACKEND")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = int(env("EMAIL_PORT"))

# ── Notifications (F4, ADR-0033); `.env.example` explains each value ─────
NOTIFICATION_POLL_SEC = int(env("NOTIFICATION_POLL_SEC"))
NOTIFICATION_PUBLIC_BASE_URL = env("NOTIFICATION_PUBLIC_BASE_URL")
NOTIFICATION_CHAT_BASE_URL = env("NOTIFICATION_CHAT_BASE_URL")
NOTIFICATION_SECRET_KEY = env("NOTIFICATION_SECRET_KEY")


# The schema of thresholds.yaml (spec §8, §13). Parsed at boot, so a missing
# or malformed file stops core-api starting instead of surfacing mid-routing.


class RoutingThresholds(BaseModel):
    t_auto: float = Field(ge=0, le=1)
    t_route: float = Field(ge=0, le=1)
    quote_match: float = Field(ge=0, le=1)


class RetrievalThresholds(BaseModel):
    # On Jev's scale, the final reranker on every run (ADR-0026).
    floor: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    # On Jev's rerank choice confidence: an auto-reply below it goes to a human.
    min_rerank_confidence: float = Field(ge=0, le=1)


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


class ClassificationThresholds(BaseModel):
    # On Jev's choice confidence, the category's classifier (ADR-0017).
    min_confidence: float = Field(ge=0, le=1)


class ClarificationThresholds(BaseModel):
    # Questions asked of a requester per ticket, then a human (ADR-0023).
    max_rounds: int = Field(ge=0)
    # How long a chat question stays open before a ticket is offered instead.
    wait_minutes: int = Field(ge=1)
    # On Jev's scale: a page is offered within this of Jev's best score.
    option_margin: float = Field(ge=0, le=1)
    # At most this many pages offered; at least 2 or nothing is asked.
    max_options: int = Field(ge=2)


class MaskingThresholds(BaseModel):
    # Above this share of a ticket's text, NER's spans (beyond the regex
    # hits) make the ticket MASK_FAILED instead of passing it on over-masked.
    ner_max_share: float = Field(gt=0, le=1)


class LifecycleThresholds(BaseModel):
    # Moves and field writes one action may set off in a chain (ADR-0028).
    max_chain_depth: int = Field(ge=1)
    # Attempts at an action that fails transiently, then the run fails.
    action_max_attempts: int = Field(ge=1)
    # How long a `require_approval` run waits before it counts as rejected.
    approval_wait_hours: int = Field(ge=1)


class AccessDeniedThresholds(BaseModel):
    # One `access_denied` audit row per user, route and method in this window.
    audit_window_seconds: int = Field(ge=1)


class PiiRevealThresholds(BaseModel):
    # Reveals one person may make in an hour; the next is refused (F5, BR-F5-07).
    max_per_user_per_hour: int = Field(ge=1)
    # How long a revealed value stays on screen.
    display_seconds: int = Field(ge=1)


class IdentityThresholds(BaseModel):
    # Minutes between Keycloak syncs; a leaver's sessions end within one (K11).
    sync_interval_minutes: int = Field(ge=1)
    # Failed passwords before a break-glass account locks, and for how long.
    local_max_failures: int = Field(ge=1)
    local_failure_window_minutes: int = Field(ge=1)
    local_lockout_minutes: int = Field(ge=1)
    # Break-glass accounts allowed at once (BR-F13-06).
    max_break_glass_accounts: int = Field(ge=0)
    # Failed sync runs in a row before identity_sync_failed is audited.
    sync_failures_before_alert: int = Field(ge=1)


class NotificationThresholds(BaseModel):
    # Sends of one email or webhook message before it is failed (F4, FR-F4-007).
    max_attempts: int = Field(ge=1)
    # A message `sending` this long has lost its worker; the sweep re-queues it.
    stuck_after_sec: int = Field(ge=1)
    # In-app messages older than this are deleted (FR-F4-010).
    in_app_retention_days: int = Field(ge=1)


class SlaThresholds(BaseModel):
    # Share of a clock's target at which its warning fires (F1, BR-F1-08).
    warn_at_percent: float = Field(gt=0, lt=100)
    # Share of the target at which a breach is escalated to managers.
    escalate_at_percent: float = Field(gt=100)
    # From this day (MM-DD) a calendar with no holidays for next year is reported.
    holidays_reminder_month_day: str = Field(pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


class RequesterThresholds(BaseModel):
    # Minutes without a turn after which a chat conversation ends (F3, BR-F3-02).
    conversation_idle_minutes: int = Field(ge=1)
    # Earlier turns of the conversation sent to ai-engine with a new one (BR-F3-01).
    max_prior_turns: int = Field(ge=0)
    # Characters of an earlier turn's answer sent with it.
    answer_excerpt_chars: int = Field(ge=0)
    # Days after resolution a requester may reopen; later, a linked ticket (BR-F3-08).
    reopen_window_days: int = Field(ge=1)
    # Days of completed tickets My tickets lists after the open ones.
    list_resolved_days: int = Field(ge=1)
    # Business days a ticket waits on its requester before it is resolved (BR-F3-11).
    auto_close_after_business_days: int = Field(ge=1)
    # A rating at or below this alerts the team lead (UC-F3-05 3x).
    low_rating_at_most: int = Field(ge=1, le=5)


class AssignmentThresholds(BaseModel):
    # Shortest note a manual reassignment carries (F2, BR-F2-05).
    reassign_note_min_chars: int = Field(ge=1)


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
    classification: ClassificationThresholds
    clarification: ClarificationThresholds
    masking: MaskingThresholds
    lifecycle: LifecycleThresholds
    access_denied: AccessDeniedThresholds
    pii_reveal: PiiRevealThresholds
    identity: IdentityThresholds
    notifications: NotificationThresholds
    assignment: AssignmentThresholds
    sla: SlaThresholds
    requester: RequesterThresholds

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

CELERY_BEAT_SCHEDULE["identity-sync"] = {
    "task": "apps.accounts.tasks.identity_sync",
    "schedule": THRESHOLDS.identity.sync_interval_minutes * 60.0,
}

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
