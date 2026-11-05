"""The Keycloak sync (F13): deactivates leavers every few minutes."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import connection, transaction

from apps.accounts.models import AuthSource, IdentitySyncRun, User
from apps.accounts.utils import SignInError
from apps.accounts.utils.oidc import AdminSession, Identities, Keycloak
from apps.audit.models import AuditLog

LOCK_KEY = "identity_sync"


@dataclass(frozen=True)
class Desired:
    """What Keycloak says about one user: why they leave, or None when they stay."""

    user: User
    reason: str | None


class SyncFailed(Exception):
    """A Keycloak read failed; the run changes nobody (BR-F13-08)."""


class IdentitySync:
    """One comparison of core-api's `oidc` users with Keycloak, then the changes it implies."""

    def __init__(self, keycloak: Keycloak, identities: Identities) -> None:
        self.keycloak = keycloak
        self.identities = identities

    def run(self) -> IdentitySyncRun | None:
        """Reads everything first and changes nobody if any read fails; None if another run
        holds the lock."""
        with self.lock() as held:
            if not held:
                return None
            users = list(
                User.objects.filter(
                    auth_source=AuthSource.OIDC.value,
                    is_active=True,
                    is_break_glass=False,
                    external_id__isnull=False,
                )
            )
            try:
                desired = self.read(users)
            except Exception as failed:
                return self.record_failure(len(users), f"{type(failed).__name__}: {failed}")
            changed, failed_users = 0, []
            for d in desired:
                try:
                    with transaction.atomic():
                        changed += self.apply(d)
                except Exception as failed:
                    failed_users.append(f"{d.user.username}: {type(failed).__name__}")
            if failed_users:
                return self.record_failure(
                    len(users), f"{len(failed_users)} user(s) failed: {'; '.join(failed_users)}"
                )
            return IdentitySyncRun.objects.create(ok=True, checked=len(users), changed=changed)

    @contextmanager
    def lock(self) -> Iterator[bool]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", [LOCK_KEY])
            held = bool(cursor.fetchone()[0])
        try:
            yield held
        finally:
            if held:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", [LOCK_KEY])

    def read(self, users: list[User]) -> list[Desired]:
        """Each user's state in Keycloak; raises SyncFailed on any failed read."""
        try:
            admin = AdminSession(self.keycloak)
        except SignInError as e:
            raise SyncFailed(e.message) from e
        try:
            return [self.read_one(user, admin) for user in users]
        except SignInError as e:
            raise SyncFailed(e.message) from e
        finally:
            admin.close()

    def read_one(self, user: User, admin: AdminSession) -> Desired:
        found = admin.get(f"/users/{user.external_id}")
        if found.status_code == 404:
            return Desired(user, "not_in_keycloak")
        self.expect_ok(found)
        if not admin.json(found).get("enabled", False):
            return Desired(user, "disabled_in_keycloak")
        return Desired(user, None)

    def expect_ok(self, response: Any) -> None:
        if response.status_code != 200:
            raise SyncFailed(f"Keycloak admin API answered {response.status_code}")

    def apply(self, desired: Desired) -> bool:
        """Deprovisions a leaver; True if anything changed."""
        if desired.reason is None:
            return False
        self.identities.deprovision(desired.user, desired.reason)
        return True

    def record_failure(self, checked: int, error: str) -> IdentitySyncRun:
        run = IdentitySyncRun.objects.create(ok=False, checked=checked, error=error[:200])
        alert_at = settings.THRESHOLDS.identity.sync_failures_before_alert
        if IdentitySyncRun.objects.failures_in_a_row() == alert_at:
            AuditLog.objects.record(
                "identity_sync_failed",
                actor_type="system",
                payload={"failures_in_a_row": alert_at, "error": run.error},
            )
        return run
