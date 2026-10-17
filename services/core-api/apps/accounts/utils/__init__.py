"""
Sign-in sessions (ADR-0029): a short-lived access token for the API, and a
rotating refresh token kept in an httpOnly cookie. Every login starts a token
family; a refresh token used twice ends its whole family.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from apps.accounts.models import AuthClient, RefreshSession, User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError


class SessionRefused(Exception):
    """A sign-in or refresh the server refuses; callers answer 401 and clear the refresh cookie."""


class SignInRefusal(StrEnum):
    LOCAL_LOGIN_DISABLED = "local_login_disabled"
    ACCOUNT_LOCKED = "account_locked"
    REDIRECT_URI_NOT_ALLOWED = "redirect_uri_not_allowed"
    OIDC_TOKEN_INVALID = "oidc_token_invalid"
    NO_ACCESS = "no_access"
    AMBIGUOUS_ROLE = "ambiguous_role"
    IDP_UNAVAILABLE = "idp_unavailable"
    LOGOUT_TOKEN_INVALID = "logout_token_invalid"


class SignInError(CodedError):
    """A sign-in core-api refuses with a code the sign-in error page names (F13)."""

    code: SignInRefusal


@dataclass(frozen=True)
class IssuedSession:
    """What a sign-in or refresh hands the browser. `refresh` is None when the browser already
    holds the newest refresh token."""

    user: User
    access: str
    access_expires_at: datetime
    refresh: str | None
    refresh_expires_at: datetime | None


@dataclass(frozen=True)
class Requester:
    """Where a sign-in or refresh came from, for the session list and the audit log."""

    user_agent: str
    ip_address: str | None


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Sessions:
    """Every sign-in, refresh, sign-out and session listing."""

    def login(
        self, username: str, password: str, client: AuthClient, requester: Requester
    ) -> IssuedSession:
        """Checks a break-glass account's password and starts a session; everyone else
        signs in through Keycloak (BR-F13-06)."""
        now = timezone.now()
        user = User.objects.filter(username=username).first()
        if user is None or not user.is_break_glass:
            self.record_failure(username, client, requester, SignInRefusal.LOCAL_LOGIN_DISABLED)
            raise SignInError(
                403, SignInRefusal.LOCAL_LOGIN_DISABLED, "sign in with your company account"
            )
        if user.is_locked(now):
            self.record_failure(username, client, requester, SignInRefusal.ACCOUNT_LOCKED)
            raise SignInError(423, SignInRefusal.ACCOUNT_LOCKED, "too many failed passwords")
        if not user.is_active or not user.check_password(password):
            self.count_failure(user, now)
            self.record_failure(username, client, requester, None)
            raise SessionRefused("invalid username or password")
        if user.failed_logins:
            user.failed_logins = 0
            user.save(update_fields=["failed_logins"])
        issued = self.start(user, client, requester, method="local")
        AuditLog.objects.record(
            "security_alert",
            actor_type="human",
            actor_id=user.id,
            payload={
                "reason": "break_glass_used",
                "client": client.value,
                "ip": requester.ip_address,
            },
        )
        return issued

    def start(
        self, user: User, client: AuthClient, requester: Requester, *, method: str
    ) -> IssuedSession:
        """Starts a new token family for a user whose identity is already checked."""
        now = timezone.now()
        family_ends = now + timedelta(hours=settings.AUTH_SESSION_MAX_HOURS)
        with transaction.atomic():
            raw, session = self.new_token(
                user, client, uuid.uuid4(), now=now, family_ends=family_ends, requester=requester
            )
            AuditLog.objects.record(
                "auth_login",
                actor_type="human",
                actor_id=user.id,
                payload={
                    "method": method,
                    "client": client.value,
                    "session": str(session.family),
                    "ip": requester.ip_address,
                },
            )
        return self.issue(session, raw)

    def count_failure(self, user: User, now: datetime) -> None:
        """Counts a failed password, locking the account at the limit (FR-F13-009)."""
        limits = settings.THRESHOLDS.identity
        user.failed_logins += 1
        if user.failed_logins >= limits.local_max_failures:
            user.locked_until = now + timedelta(minutes=limits.local_lockout_minutes)
            user.failed_logins = 0
        user.save(update_fields=["failed_logins", "locked_until"])

    def record_failure(
        self, username: str, client: AuthClient, requester: Requester, code: SignInRefusal | None
    ) -> None:
        AuditLog.objects.record(
            "auth_login_failed",
            actor_type="human",
            payload={
                "username": username[:150],
                "client": client.value,
                "ip": requester.ip_address,
                "reason": code.value if code else "invalid_credentials",
            },
        )

    def refresh(self, raw: str, client: AuthClient, requester: Requester) -> IssuedSession:
        """Swaps a refresh token for a new access token and a new refresh token."""
        reused: RefreshSession | None = None
        issued: IssuedSession | None = None
        with transaction.atomic():
            session = (
                RefreshSession.objects.select_for_update()
                .select_related("user")
                .filter(token_hash=token_hash(raw), client=client.value)
                .first()
            )
            now = timezone.now()
            if session is None or session.revoked_at is not None:
                raise SessionRefused("unknown or revoked refresh token")
            if session.rotated_at is not None:
                grace = timedelta(seconds=settings.AUTH_REFRESH_REUSE_GRACE_SEC)
                live = RefreshSession.objects.live_family(session.family).exists()
                if now - session.rotated_at <= grace and live and session.user.is_active:
                    issued = self.issue(session, None)
                else:
                    self.revoke_family(session.family, "refresh_reuse_detected")
                    reused = session
            elif session.expires_at <= now or session.family_expires_at <= now:
                raise SessionRefused("refresh token expired")
            elif not session.user.is_active:
                self.revoke_family(session.family, "user_inactive")
                raise SessionRefused("user is inactive")
            else:
                session.rotated_at = now
                session.save(update_fields=["rotated_at"])
                raw_new, successor = self.new_token(
                    session.user,
                    client,
                    session.family,
                    now=now,
                    family_ends=session.family_expires_at,
                    requester=requester,
                )
                issued = self.issue(successor, raw_new)
        if reused is not None:
            AuditLog.objects.record(
                "security_alert",
                actor_type="system",
                actor_id=reused.user_id,
                payload={
                    "reason": "refresh_token_reused",
                    "session": str(reused.family),
                    "client": client.value,
                    "ip": requester.ip_address,
                },
            )
            raise SessionRefused("refresh token reused: every token of this sign-in is revoked")
        assert issued is not None
        return issued

    def logout(self, raw: str, client: AuthClient) -> None:
        """Ends the sign-in a refresh token belongs to; an unknown token is ignored."""
        session = RefreshSession.objects.filter(
            token_hash=token_hash(raw), client=client.value
        ).first()
        if session is None:
            return
        self.revoke_family(session.family, "logout")
        AuditLog.objects.record(
            "auth_logout",
            actor_type="human",
            actor_id=session.user_id,
            payload={"client": client.value, "session": str(session.family)},
        )

    def end(self, user: User, family: uuid.UUID) -> int:
        """Ends one of `user`'s sign-ins; returns how many tokens it revoked."""
        if not RefreshSession.objects.filter(user=user, family=family).exists():
            return 0
        count = self.revoke_family(family, "ended_by_user")
        AuditLog.objects.record(
            "auth_session_ended",
            actor_type="human",
            actor_id=user.id,
            payload={"session": str(family)},
        )
        return count

    def end_all(self, user: User) -> int:
        """Ends every sign-in of `user`; returns how many tokens it revoked."""
        count = self.revoke_user(user, "logout_everywhere")
        AuditLog.objects.record("auth_logout_everywhere", actor_type="human", actor_id=user.id)
        return count

    def revoke_user(self, user: User, reason: str) -> int:
        """Revokes every live token of `user`; the caller audits why."""
        return RefreshSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now(), revoke_reason=reason
        )

    def live(self, user: User) -> list[RefreshSession]:
        """The newest token of each of `user`'s live sign-ins, newest sign-in first."""
        newest: dict[uuid.UUID, RefreshSession] = {}
        for session in RefreshSession.objects.filter(
            user=user,
            revoked_at__isnull=True,
            rotated_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).order_by("-created_at"):
            newest.setdefault(session.family, session)
        return list(newest.values())

    def revoke_family(self, family: uuid.UUID, reason: str) -> int:
        return RefreshSession.objects.filter(family=family, revoked_at__isnull=True).update(
            revoked_at=timezone.now(), revoke_reason=reason
        )

    def new_token(
        self,
        user: User,
        client: AuthClient,
        family: uuid.UUID,
        *,
        now: datetime,
        family_ends: datetime,
        requester: Requester,
    ) -> tuple[str, RefreshSession]:
        """A fresh refresh token in `family`, idle-limited and never outliving the family."""
        raw = secrets.token_urlsafe(48)
        session = RefreshSession.objects.create(
            user=user,
            client=client.value,
            family=family,
            token_hash=token_hash(raw),
            expires_at=min(now + timedelta(hours=settings.AUTH_REFRESH_IDLE_HOURS), family_ends),
            family_expires_at=family_ends,
            user_agent=requester.user_agent[:255],
            ip_address=requester.ip_address,
        )
        return raw, session

    def issue(self, session: RefreshSession, raw: str | None) -> IssuedSession:
        """An access token bound to `session`'s family, with the refresh token to hand over."""
        # ninja_jwt annotates for_user as returning the class; it returns a token.
        access = cast(AccessToken, AccessToken.for_user(session.user))  # type: ignore[misc]
        access["sid"] = str(session.family)
        return IssuedSession(
            user=session.user,
            access=str(access),
            access_expires_at=datetime.fromtimestamp(access["exp"], tz=UTC),
            refresh=raw,
            refresh_expires_at=session.expires_at if raw is not None else None,
        )


# --- the sessions service ---

sessions = Sessions()
