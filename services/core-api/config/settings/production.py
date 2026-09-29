import os

from .base import *  # noqa: F403

DEBUG = False

if SECRET_KEY == "dev-only-insecure-secret-key-change-me":  # noqa: F405
    raise RuntimeError("SECRET_KEY must be set explicitly in production")

if os.environ.get("PII_ENCRYPTION_KEY", "") == "Zm9yLWRldi1vbmx5LTMyLWJ5dGUta2V5LWhlcmUhISE=":
    raise RuntimeError("PII_ENCRYPTION_KEY must be set explicitly in production")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
