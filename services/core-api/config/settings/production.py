from .base import *  # noqa: F403

DEBUG = False

# The public dev values from .env.example, a denylist, never a default.
# apps/core/tests/test_settings_env.py keeps it equal to the template, so a
# dev value changed there can't quietly get through here.
DEV_ONLY_SECRETS = {
    "SECRET_KEY": "dev-only-insecure-secret-key-change-me",
    "PII_ENCRYPTION_KEY": "Zm9yLWRldi1vbmx5LTMyLWJ5dGUta2V5LWhlcmUhISE=",
}
for _key, _dev_value in DEV_ONLY_SECRETS.items():
    if env(_key) == _dev_value:  # noqa: F405
        raise RuntimeError(f"{_key} must be set explicitly in production")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
