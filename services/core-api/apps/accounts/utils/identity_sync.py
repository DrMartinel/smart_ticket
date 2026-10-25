"""The Keycloak sync (F13): deactivates leavers and applies changed rights every few minutes."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import connection, transaction

from apps.accounts.models import AuthSource, IdentitySyncRun, User
from apps.accounts.utils import SignInError, SignInRefusal, sessions
from apps.accounts.utils.oidc import (
    AdminSession,
    Identities,
    Keycloak,
    Rights,
    rights_from_claims,
)
from apps.audit.models import AuditLog

LOCK_KEY = "identity_sync"


@dataclass(frozen=True)
class Desired:
    """What Keycloak says about one user: gone or disabled, refused rights, or rights."""

    user: User
    rights: Rights | None
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
                    auth_source=AuthSource.OIDC.value, is_active=True, is_break_glass=False
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
            client_uuid = self.client_uuid(admin)
            return [self.read_one(user, admin, client_uuid) for user in users]
        except SignInError as e:
            raise SyncFailed(e.message) from e
        finally:
            admin.close()

    def client_uuid(self, admin: AdminSession) -> str:
        response = admin.get(f"/clients?clientId={settings.OIDC_CLIENT_ID}")
        found = admin.json(response) if response.status_code == 200 else []
        if not found:
            raise SyncFailed(f"client lookup answered {response.status_code}")
        return str(found[0]["id"])

    def read_one(self, user: User, admin: AdminSession, client_uuid: str) -> Desired:
        found = admin.get(f"/users/{user.external_id}")
        if found.status_code == 404:
            return Desired(user, None, "not_in_keycloak")
        self.expect_ok(found)
        if not admin.json(found).get("enabled", False):
            return Desired(user, None, "disabled_in_keycloak")
        roles = admin.get(
            f"/users/{user.external_id}/role-mappings/clients/{client_uuid}/composite"
        )
        groups = admin.get(f"/users/{user.external_id}/groups")
        self.expect_ok(roles)
        self.expect_ok(groups)
        claims: dict[str, Any] = {
            "resource_access": {
                settings.OIDC_CLIENT_ID: {"roles": [r["name"] for r in admin.json(roles)]}
            },
            "groups": [g["path"] for g in admin.json(groups)],
        }
        try:
            return Desired(user, rights_from_claims(claims, settings.OIDC_CLIENT_ID), None)
        except SignInError as refused:
            return Desired(user, None, refused.code.value)

    def expect_ok(self, response: Any) -> None:
        if response.status_code != 200:
            raise SyncFailed(f"Keycloak admin API answered {response.status_code}")

    def apply(self, desired: Desired) -> bool:
        """Deprovisions, or applies changed rights and ends sessions; True if anything changed."""
        user = desired.user
        if desired.rights is None:
            self.identities.deprovision(user, desired.reason or "no_access")
            if desired.reason == SignInRefusal.AMBIGUOUS_ROLE.value:
                AuditLog.objects.record(
                    "security_alert",
                    actor_type="system",
                    actor_id=user.id,
                    payload={"reason": "ambiguous_role", "source": "identity_sync"},
                )
            return True
        if self.identities.apply(user, desired.rights):
            sessions.revoke_user(user, "rights_changed")
            return True
        return False

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
