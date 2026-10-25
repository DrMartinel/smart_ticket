"""Celery entry points for accounts."""

from celery import shared_task

from apps.accounts.utils.identity_sync import IdentitySync
from apps.accounts.utils.oidc import Identities, keycloak


@shared_task
def identity_sync() -> int:
    """Compares active `oidc` users with Keycloak and applies the differences (F13)."""
    run = IdentitySync(keycloak, Identities()).run()
    return run.changed if run else 0
