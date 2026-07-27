"""
Base Django settings. Environment-specific overrides live in dev.py / prod.py.

Everything that varies between environments is read from os.environ here,
with dev-safe defaults — those defaults are NOT meant to be used in prod
(see prod.py, which fails loudly if left unset).
"""

import os
from pathlib import Path

import yaml
from contracts.routing import Thresholds

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
    "apps.audit.middleware.TraceIdMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
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


def _parse_database_url(url: str) -> dict:
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
CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS", "http://localhost:3000"
).split(",")

# ── Smart Triage domain settings ────────────────────────────────────────
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"
AI_ENGINE_URL = os.environ.get("AI_ENGINE_URL", "http://localhost:8001")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_NER_MODEL = os.environ.get("OLLAMA_NER_MODEL", "qwen3:8b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "ollama")  # "ollama" | "stub"
PII_ENCRYPTION_KEY = os.environ.get(
    "PII_ENCRYPTION_KEY", "Zm9yLWRldi1vbmx5LTMyLWJ5dGUta2V5LWhlcmUhISE="
)
PII_QUARANTINE_TTL_HOURS = int(os.environ.get("PII_QUARANTINE_TTL_HOURS", "72"))
AI_ENGINE_RO_PASSWORD = os.environ.get("POSTGRES_AI_RO_PASSWORD", "ai_engine_ro_password")
DB_APP_ROLE = DATABASES["default"]["USER"]

THRESHOLDS_PATH = os.environ.get(
    "THRESHOLDS_PATH", str(BASE_DIR / "config" / "thresholds.yaml")
)


def load_thresholds() -> Thresholds:
    with open(THRESHOLDS_PATH) as f:
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
