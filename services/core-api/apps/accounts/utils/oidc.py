"""Sign-in through Keycloak (F13, ADR-0032): code exchange, token checks, rights from claims."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import AuthClient, AuthSource, Capability, User, UserCapability, UserRole
from apps.accounts.utils import IssuedSession, Requester, SignInError, SignInRefusal, sessions
from apps.audit.models import AuditLog
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

    @property
    def realm_path(self) -> str:
        return urlparse(settings.OIDC_ISSUER_URL).path

    def http(self) -> httpx.Client:
        timeout = httpx.Timeout(
            settings.OIDC_HTTP_READ_TIMEOUT_SEC, connect=settings.OIDC_HTTP_CONNECT_TIMEOUT_SEC
        )
        return httpx.Client(timeout=timeout, follow_redirects=False)

    def call(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """One request; an outage or a 5xx is `idp_unavailable`."""
        try:
            with self.http() as client:
                response = client.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "Keycloak is unreachable") from e
        if response.status_code >= 500:
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "Keycloak answered an error")
        return response

    def discovery(self, *, fresh: bool = False) -> dict[str, Any]:
        """The realm's OpenID configuration, cached with the signing keys unless `fresh`."""
        if fresh or self._discovery is None or self.stale():
            url = f"{settings.OIDC_SERVER_URL}{self.realm_path}/.well-known/openid-configuration"
            response = self.call("GET", url)
            if response.status_code != 200:
                raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "no OpenID configuration")
            self._discovery = response.json()
            self._keys = {}
            self._fetched_at = time.monotonic()
        return self._discovery

    def stale(self) -> bool:
        return time.monotonic() - self._fetched_at > settings.OIDC_JWKS_CACHE_SEC

    def signing_key(self, kid: str | None) -> jwt.PyJWK | None:
        """The realm key with this id; an unknown id refetches the key set once."""
        if kid not in self._keys or self.stale():
            response = self.call("GET", self.discovery()["jwks_uri"])
            if response.status_code != 200:
                raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "no signing keys")
            self._keys = {
                k["kid"]: jwt.PyJWK(k)
                for k in response.json().get("keys", [])
                if k.get("use", "sig") == "sig" and k.get("alg", "RS256") == "RS256"
            }
            self._fetched_at = time.monotonic()
        return self._keys.get(kid) if kid else None

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
        id_token = response.json().get("id_token") if response.status_code == 200 else None
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
                leeway=60,
                options={"require": ["iss", "aud", "iat", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise SignInError(status, refusal, "the token failed verification") from e

    def admin_get(self, path: str, token: str) -> httpx.Response:
        return self.call(
            "GET",
            f"{settings.OIDC_SERVER_URL}/admin{self.realm_path}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )

    def admin_token(self) -> str:
        """A service-account token for the admin API (`smart-ticket-sync`)."""
        response = self.call(
            "POST",
            self.discovery()["token_endpoint"],
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
            },
        )
        token = response.json().get("access_token") if response.status_code == 200 else None
        if not isinstance(token, str):
            raise SignInError(502, SignInRefusal.IDP_UNAVAILABLE, "the sync client was refused")
        return token


class Identities:
    """Users created, linked, granted and deprovisioned from Keycloak (F13)."""

    def find_or_provision(self, claims: dict[str, Any], rights: Rights) -> User:
        """The user for `sub`; else links a local user by verified email; else creates one."""
        sub = claims["sub"]
        user = User.objects.filter(external_id=sub).first()
        if user is None and claims.get("email_verified") and claims.get("email"):
            user = User.objects.filter(
                email__iexact=claims["email"], external_id__isnull=True
            ).first()
            if user is not None:
                user.external_id = sub
                user.auth_source = AuthSource.OIDC.value
                user.save(update_fields=["external_id", "auth_source"])
                self.audit("identity_linked", user, {"sub": sub})
        created = user is None
        if user is None:
            user = self.create(claims)
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        self.apply(user, rights, audit=not created)
        return user

    def create(self, claims: dict[str, Any]) -> User:
        """A new user named after `preferred_username`, suffixed when the name is taken."""
        sub = claims["sub"]
        username = claims.get("preferred_username") or sub
        if User.objects.filter(username=username).exists():
            username = f"{username}-{sub.replace('-', '')[:4]}"
        first, _, last = (claims.get("name") or "").rpartition(" ")
        user = User.objects.create_user(
            username=username,
            email=claims.get("email", ""),
            first_name=claims.get("given_name") or first,
            last_name=claims.get("family_name") or last,
            external_id=sub,
            auth_source=AuthSource.OIDC.value,
        )
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
            "authorize_url": self.keycloak.discovery(fresh=True)["authorization_endpoint"],
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
