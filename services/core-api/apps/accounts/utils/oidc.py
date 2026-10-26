"""Sign-in through Keycloak (F13, ADR-0032): code exchange, token checks, rights from claims."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import AuthClient, AuthSource, Capability, User, UserCapability, UserRole
from apps.accounts.utils import IssuedSession, Requester, SignInError, SignInRefusal, sessions
from apps.audit.models import AuditLog
from apps.notifications.utils.notifier import notifier
from apps.teams.models import MembershipRole, Team, TeamMembership

LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"
TEAM_PREFIX = "/it/"


@dataclass(frozen=True)
class Rights:
    """What a user may do, read from Keycloak's roles and groups (BR-F13-02, 03)."""

    role: UserRole
    capabilities: frozenset[Capability] = frozenset()
    teams: dict[str, MembershipRole] = field(default_factory=dict)
    ignored: tuple[str, ...] = ()


def rights_from_claims(claims: dict[str, Any], client_id: str) -> Rights:
    """One primary role, any capabilities, and `/it/<team>[/lead]` groups; refuses none or two roles."""
    roles = set(claims.get("resource_access", {}).get(client_id, {}).get("roles", []))
    primary = sorted(roles & {r.value for r in UserRole})
    if not primary:
        raise SignInError(403, SignInRefusal.NO_ACCESS, "no Smart Ticket role in Keycloak")
    if len(primary) > 1:
        raise SignInError(
            403,
            SignInRefusal.AMBIGUOUS_ROLE,
            "more than one Smart Ticket role in Keycloak",
            {"roles": primary},
        )
    capabilities = frozenset(Capability(r) for r in roles & {c.value for c in Capability})
    teams: dict[str, MembershipRole] = {}
    ignored = sorted(roles - set(primary) - {c.value for c in capabilities})
    for group in claims.get("groups", []):
        parts = group.removeprefix(TEAM_PREFIX).split("/") if group.startswith(TEAM_PREFIX) else []
        if len(parts) == 1 and parts[0]:
            teams.setdefault(parts[0], MembershipRole.MEMBER)
        elif len(parts) == 2 and parts[0] and parts[1] == "lead":
            teams[parts[0]] = MembershipRole.LEAD
        else:
            ignored.append(group)
    return Rights(UserRole(primary[0]), capabilities, teams, tuple(ignored))


class Keycloak:
    """core-api's calls to Keycloak: discovery, code exchange, signing keys, admin reads."""

    def __init__(self) -> None:
        self._discovery: dict[str, Any] | None = None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._failed_at: float | None = None
        self._lock = threading.Lock()

    @property
    def realm_path(self) -> str:
        return urlparse(settings.OIDC_ISSUER_URL).path

    def http(self) -> httpx.Client:
        timeout = httpx.Timeout(
            settings.OIDC_HTTP_READ_TIMEOUT_SEC, connect=settings.OIDC_HTTP_CONNECT_TIMEOUT_SEC
        )
        return httpx.Client(timeout=timeout, follow_redirects=False)

    def call(
        self, method: str, url: str, *, client: httpx.Client | None = None, **kwargs: Any
    ) -> httpx.Response:
        """One request; an outage or a 5xx is `idp_unavailable`."""
        try:
            if client is not None:
                response = client.request(method, url, **kwargs)
            else:
                with self.http() as own:
                    response = own.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "Keycloak is unreachable") from e
        if response.status_code >= 500:
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "Keycloak answered an error")
        return response

    def json_of(self, response: httpx.Response) -> Any:
        """The response's JSON; anything else is `idp_unavailable`."""
        try:
            return response.json()
        except ValueError as e:
            raise SignInError(
                502, SignInRefusal.IDP_UNAVAILABLE, "Keycloak answered non-JSON"
            ) from e

    def age(self) -> float:
        return time.monotonic() - self._fetched_at

    def discovery(self, *, max_age: float | None = None) -> dict[str, Any]:
        """The realm's OpenID configuration and keys, refetched past `max_age` seconds
        (by default the key cache's)."""
        limit = settings.OIDC_JWKS_CACHE_SEC if max_age is None else max_age
        with self._lock:
            if self._discovery is None or self.age() > limit:
                if self.failed_recently():
                    raise SignInError(
                        502, SignInRefusal.IDP_UNAVAILABLE, "Keycloak was unreachable moments ago"
                    )
                self.refresh()
            assert self._discovery is not None
            return self._discovery

    def failed_recently(self) -> bool:
        return (
            self._failed_at is not None
            and time.monotonic() - self._failed_at < settings.OIDC_MIN_REFETCH_SEC
        )

    def refresh(self) -> None:
        """Fetches the OpenID configuration and the signing keys, remembering a failure;
        the caller holds the lock."""
        try:
            discovery, keys = self.fetch()
        except SignInError:
            self._failed_at = time.monotonic()
            raise
        self._discovery, self._keys = discovery, keys
        self._fetched_at = time.monotonic()
        self._failed_at = None

    def fetch(self) -> tuple[dict[str, Any], dict[str, jwt.PyJWK]]:
        """The OpenID configuration and its signing keys; a missing or malformed answer is
        `idp_unavailable`."""
        url = f"{settings.OIDC_SERVER_URL}{self.realm_path}/.well-known/openid-configuration"
        response = self.call("GET", url)
        discovery = self.json_of(response) if response.status_code == 200 else None
        endpoints = ("authorization_endpoint", "token_endpoint", "jwks_uri")
        if not isinstance(discovery, dict) or not all(
            isinstance(discovery.get(e), str) for e in endpoints
        ):
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "no OpenID configuration")
        response = self.call("GET", discovery["jwks_uri"])
        key_set = self.json_of(response) if response.status_code == 200 else None
        if not isinstance(key_set, dict) or not isinstance(key_set.get("keys"), list):
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "no signing keys")
        keys = {
            k["kid"]: jwt.PyJWK(k)
            for k in key_set["keys"]
            if isinstance(k, dict)
            and "kid" in k
            and k.get("use", "sig") == "sig"
            and k.get("alg", "RS256") == "RS256"
        }
        return discovery, keys

    def signing_key(self, kid: str | None) -> jwt.PyJWK | None:
        """The realm key with this id; an unknown id refetches the keys at most once per
        OIDC_MIN_REFETCH_SEC."""
        self.discovery()
        with self._lock:
            if kid and kid in self._keys:
                return self._keys[kid]
            if not kid or self.age() < settings.OIDC_MIN_REFETCH_SEC:
                return None
            self.refresh()
            return self._keys.get(kid)

    def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> str:
        """The ID token for an authorization code; the other tokens are dropped (BR-F13-01)."""
        response = self.call(
            "POST",
            self.discovery()["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "client_id": settings.OIDC_CLIENT_ID,
                "client_secret": settings.OIDC_CLIENT_SECRET,
            },
        )
        id_token = self.json_of(response).get("id_token") if response.status_code == 200 else None
        if not isinstance(id_token, str):
            raise SignInError(401, SignInRefusal.OIDC_TOKEN_INVALID, "the sign-in code was refused")
        return id_token

    def verify(self, token: str, refusal: SignInRefusal, status: int = 401) -> dict[str, Any]:
        """The claims of a token Keycloak signed for this client, still valid, else `refusal`."""
        try:
            header = jwt.get_unverified_header(token)
            key = self.signing_key(header.get("kid"))
            if key is None or header.get("alg") != "RS256":
                raise jwt.InvalidTokenError("unknown signing key")
            return jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=settings.OIDC_CLIENT_ID,
                issuer=settings.OIDC_ISSUER_URL,
                leeway=settings.OIDC_CLOCK_SKEW_SEC,
                options={"require": ["iss", "aud", "iat", "exp", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise SignInError(status, refusal, "the token failed verification") from e

    def admin_get(self, path: str, token: str, client: httpx.Client) -> httpx.Response:
        return self.call(
            "GET",
            f"{settings.OIDC_SERVER_URL}/admin{self.realm_path}{path}",
            client=client,
            headers={"Authorization": f"Bearer {token}"},
        )

    def admin_token(self, client: httpx.Client) -> str:
        """A service-account token for the admin API (`smart-ticket-sync`)."""
        response = self.call(
            "POST",
            self.discovery()["token_endpoint"],
            client=client,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
            },
        )
        token = self.json_of(response).get("access_token") if response.status_code == 200 else None
        if not isinstance(token, str):
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "the sync client was refused")
        return token


class AdminSession:
    """One sync run's admin API access: one connection, and a new token when Keycloak
    answers 401."""

    def __init__(self, keycloak: Keycloak) -> None:
        self.keycloak = keycloak
        self.client = keycloak.http()
        self.token = keycloak.admin_token(self.client)

    def get(self, path: str) -> httpx.Response:
        response = self.keycloak.admin_get(path, self.token, self.client)
        if response.status_code == 401:
            self.token = self.keycloak.admin_token(self.client)
            response = self.keycloak.admin_get(path, self.token, self.client)
        return response

    def json(self, response: httpx.Response) -> Any:
        return self.keycloak.json_of(response)

    def close(self) -> None:
        self.client.close()


class Identities:
    """Users created, linked, granted and deprovisioned from Keycloak (F13)."""

    def find_or_provision(self, claims: dict[str, Any], rights: Rights) -> User:
        """The user for `sub`; else links a local user by verified email; else creates one."""
        user = User.objects.filter(external_id=claims["sub"]).first() or self.link(claims)
        created = user is None
        if user is None:
            user = self.create(claims)
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        self.apply(user, rights, audit=not created)
        return user

    def link(self, claims: dict[str, Any]) -> User | None:
        """The one active local user with this verified email, now linked to `sub`; never a
        break-glass account, and nobody when the email is ambiguous."""
        if not (claims.get("email_verified") and claims.get("email")):
            return None
        candidates = list(
            User.objects.filter(email__iexact=claims["email"], external_id__isnull=True)[:2]
        )
        if len(candidates) != 1:
            if candidates:
                self.skip_link(claims, "ambiguous_email")
            return None
        user = candidates[0]
        if user.is_break_glass or not user.is_active:
            self.skip_link(claims, "break_glass" if user.is_break_glass else "inactive")
            return None
        user.external_id = claims["sub"]
        user.auth_source = AuthSource.OIDC.value
        user.set_unusable_password()
        user.save(update_fields=["external_id", "auth_source", "password"])
        self.audit("identity_linked", user, {"sub": claims["sub"]})
        return user

    def skip_link(self, claims: dict[str, Any], reason: str) -> None:
        AuditLog.objects.record(
            "identity_link_skipped",
            actor_type="system",
            payload={"sub": claims["sub"], "reason": reason},
        )

    def create(self, claims: dict[str, Any]) -> User:
        """A new user named after `preferred_username`, suffixed when the name is taken."""
        sub = claims["sub"]
        username = claims.get("preferred_username") or sub
        if User.objects.filter(username=username).exists():
            username = f"{username}-{sub.replace('-', '')[:8]}"
        first, _, last = (claims.get("name") or "").rpartition(" ")
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=claims.get("email", ""),
                    first_name=claims.get("given_name") or first,
                    last_name=claims.get("family_name") or last,
                    external_id=sub,
                    auth_source=AuthSource.OIDC.value,
                )
        except IntegrityError:
            existing = User.objects.filter(external_id=sub).first()
            if existing is None:
                raise
            return existing
        user.set_unusable_password()
        user.save(update_fields=["password"])
        self.audit("identity_provisioned", user, {"sub": sub, "username": username})
        return user

    def apply(self, user: User, rights: Rights, *, audit: bool = True) -> bool:
        """Sets role, capabilities and team memberships from `rights`; True if role or
        capabilities changed (BR-F13-05)."""
        before_caps = user.capability_set()
        changed = user.role != rights.role.value or before_caps != {
            c.value for c in rights.capabilities
        }
        before = {"role": user.role, "capabilities": sorted(before_caps)}
        user.role = rights.role.value
        user.rights_synced_at = timezone.now()
        user.save(update_fields=["role", "rights_synced_at"])
        UserCapability.objects.filter(user=user, source="keycloak").exclude(
            capability__in=[c.value for c in rights.capabilities]
        ).delete()
        for capability in rights.capabilities:
            UserCapability.objects.get_or_create(
                user=user, capability=capability.value, defaults={"source": "keycloak"}
            )
        teams = {t.slug: t for t in Team.objects.filter(slug__in=rights.teams, is_active=True)}
        TeamMembership.objects.filter(user=user, source="keycloak").exclude(
            team__slug__in=teams
        ).delete()
        for slug, team in teams.items():
            TeamMembership.objects.update_or_create(
                team=team,
                user=user,
                defaults={"role": rights.teams[slug].value, "source": "keycloak"},
            )
        if changed and audit:
            after = {
                "role": user.role,
                "capabilities": sorted(c.value for c in rights.capabilities),
            }
            self.audit("identity_rights_changed", user, {"before": before, "after": after})
        return changed

    def deprovision(self, user: User, reason: str) -> None:
        """Deactivates the user and ends every sign-in (BR-F13-05)."""
        with transaction.atomic():
            user.is_active = False
            user.save(update_fields=["is_active"])
            sessions.revoke_user(user, "idp_deprovisioned")
            self.audit("identity_deactivated", user, {"reason": reason})

    def audit(self, event: str, user: User, payload: dict[str, Any]) -> None:
        AuditLog.objects.record(event, actor_type="system", actor_id=user.id, payload=payload)


class OidcSignIn:
    """The Keycloak sign-in: exchange a code for a core-api session, and back-channel logout."""

    def __init__(self, keycloak: Keycloak, identities: Identities) -> None:
        self.keycloak = keycloak
        self.identities = identities

    def config(self) -> dict[str, Any]:
        return {
            "issuer": settings.OIDC_ISSUER_URL,
            "client_id": settings.OIDC_CLIENT_ID,
            "authorize_url": self.keycloak.discovery(max_age=settings.OIDC_MIN_REFETCH_SEC)[
                "authorization_endpoint"
            ],
            "scopes": "openid profile email",
        }

    def exchange(
        self,
        *,
        code: str,
        verifier: str,
        nonce: str,
        redirect_uri: str,
        client: AuthClient,
        requester: Requester,
    ) -> IssuedSession:
        """Verifies the ID token, maps its rights, and starts an ADR-0029 session."""
        if redirect_uri not in settings.OIDC_REDIRECT_URIS:
            raise SignInError(400, SignInRefusal.REDIRECT_URI_NOT_ALLOWED, "unknown redirect_uri")
        claims = self.keycloak.verify(
            self.keycloak.exchange_code(code, verifier, redirect_uri),
            SignInRefusal.OIDC_TOKEN_INVALID,
        )
        if not nonce or claims.get("nonce") != nonce:
            raise SignInError(401, SignInRefusal.OIDC_TOKEN_INVALID, "nonce mismatch")
        try:
            rights = rights_from_claims(claims, settings.OIDC_CLIENT_ID)
        except SignInError as refused:
            self.record_refusal(claims, refused, client, requester)
            raise
        glass = User.objects.filter(external_id=claims["sub"], is_break_glass=True).first()
        if glass is not None:
            AuditLog.objects.record(
                "security_alert",
                actor_type="system",
                actor_id=glass.id,
                payload={"reason": "break_glass_account_in_keycloak", "sub": claims["sub"]},
            )
            notifier.security_alert(
                "break_glass_account_in_keycloak",
                actor="system",
                detail=f"{glass.username} signed in through Keycloak",
            )
            raise SignInError(
                403, SignInRefusal.NO_ACCESS, "a break-glass account can't sign in through Keycloak"
            )
        with transaction.atomic():
            user = self.identities.find_or_provision(claims, rights)
        if rights.ignored:
            AuditLog.objects.record(
                "identity_claims_ignored",
                actor_type="system",
                actor_id=user.id,
                payload={"ignored": list(rights.ignored)},
            )
        return sessions.start(user, client, requester, method="oidc")

    def record_refusal(
        self,
        claims: dict[str, Any],
        refused: SignInError,
        client: AuthClient,
        requester: Requester,
    ) -> None:
        event = (
            "security_alert"
            if refused.code is SignInRefusal.AMBIGUOUS_ROLE
            else "auth_login_failed"
        )
        AuditLog.objects.record(
            event,
            actor_type="system",
            payload={
                "reason": refused.code.value,
                "sub": claims.get("sub"),
                "username": claims.get("preferred_username"),
                "client": client.value,
                "ip": requester.ip_address,
            },
        )
        if refused.code is SignInRefusal.AMBIGUOUS_ROLE:
            notifier.security_alert(
                refused.code.value,
                actor="system",
                detail=f"{claims.get('preferred_username')} holds more than one role in Keycloak",
            )

    def backchannel_logout(self, logout_token: str) -> int:
        """Ends every sign-in of the user Keycloak logged out; returns tokens revoked."""
        claims = self.keycloak.verify(logout_token, SignInRefusal.LOGOUT_TOKEN_INVALID, 400)
        if LOGOUT_EVENT not in claims.get("events", {}) or "nonce" in claims:
            raise SignInError(400, SignInRefusal.LOGOUT_TOKEN_INVALID, "not a logout token")
        user = User.objects.filter(external_id=claims["sub"]).first()
        if user is None:
            return 0
        count = sessions.revoke_user(user, "idp_logout")
        AuditLog.objects.record(
            "auth_backchannel_logout",
            actor_type="system",
            actor_id=user.id,
            payload={"revoked": count},
        )
        return count


keycloak = Keycloak()
oidc_sign_in = OidcSignIn(keycloak, Identities())
