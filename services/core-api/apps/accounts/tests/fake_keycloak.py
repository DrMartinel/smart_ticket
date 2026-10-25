"""An in-memory Keycloak realm for tests: discovery, JWKS, code exchange and the admin API."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings

CLIENT_UUID = "7c1f5d2e-0000-4000-8000-000000000001"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class Person:
    username: str
    roles: list[str]
    groups: list[str] = field(default_factory=list)
    sub: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    email_verified: bool = True
    name: str = ""
    enabled: bool = True


@dataclass
class FakeKeycloak:
    """Answers core-api's Keycloak calls; `down` makes every call fail to connect."""

    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = "kid-1"
    people: dict[str, Person] = field(default_factory=dict)
    codes: dict[str, tuple[Person, str]] = field(default_factory=dict)
    down: bool = False
    admin_status: int = 200
    admin_expired_once: bool = False
    garbled: bool = False
    admin_tokens: int = 0
    attempts: int = 0
    calls: list[str] = field(default_factory=list)

    @property
    def base(self) -> str:
        return f"{settings.OIDC_SERVER_URL}{urlparse(settings.OIDC_ISSUER_URL).path}"

    def add(self, person: Person) -> Person:
        if not person.email:
            person.email = f"{person.username}@congty.vn"
        self.people[person.sub] = person
        return person

    def code_for(self, person: Person, nonce: str = "nonce-1") -> str:
        code = f"code-{uuid.uuid4()}"
        self.codes[code] = (person, nonce)
        return code

    def sign(
        self, claims: dict[str, Any], key: rsa.RSAPrivateKey | None = None, kid: str | None = None
    ) -> str:
        return jwt.encode(
            claims, key or self.key, algorithm="RS256", headers={"kid": kid or self.kid}
        )

    def id_token(self, person: Person, nonce: str, **overrides: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": settings.OIDC_ISSUER_URL,
            "aud": settings.OIDC_CLIENT_ID,
            "sub": person.sub,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "preferred_username": person.username,
            "email": person.email,
            "email_verified": person.email_verified,
            "name": person.name,
            "resource_access": {settings.OIDC_CLIENT_ID: {"roles": person.roles}},
            "groups": person.groups,
        }
        claims.update(overrides)
        return self.sign(claims)

    def logout_token(self, person: Person, **overrides: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": settings.OIDC_ISSUER_URL,
            "aud": settings.OIDC_CLIENT_ID,
            "sub": person.sub,
            "iat": now,
            "exp": now + 300,
            "jti": str(uuid.uuid4()),
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        }
        claims.update(overrides)
        return self.sign(claims)

    def jwks(self) -> dict[str, Any]:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.down:
            raise httpx.ConnectError("keycloak is down", request=request)
        url = str(request.url)
        self.calls.append(f"{request.method} {url}")
        if self.garbled:
            return httpx.Response(200, text="<html>proxy error</html>")
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": settings.OIDC_ISSUER_URL,
                    "authorization_endpoint": f"{self.base}/protocol/openid-connect/auth",
                    "token_endpoint": f"{self.base}/protocol/openid-connect/token",
                    "jwks_uri": f"{self.base}/protocol/openid-connect/certs",
                },
            )
        if url.endswith("/protocol/openid-connect/certs"):
            return httpx.Response(200, json=self.jwks())
        if url.endswith("/protocol/openid-connect/token"):
            return self.token(request)
        if "/admin/" in url:
            return self.admin(
                urlparse(url).path.split(urlparse(settings.OIDC_ISSUER_URL).path, 1)[1]
            )
        return httpx.Response(404)

    def token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if form.get("grant_type") == "client_credentials":
            self.admin_tokens += 1
            return httpx.Response(200, json={"access_token": f"admin-token-{self.admin_tokens}"})
        found = self.codes.pop(form.get("code", ""), None)
        if found is None:
            return httpx.Response(400, json={"error": "invalid_grant"})
        person, nonce = found
        return httpx.Response(
            200, json={"id_token": self.id_token(person, nonce), "access_token": "x"}
        )

    def admin(self, path: str) -> httpx.Response:
        if self.admin_expired_once and "/users/" in path:
            self.admin_expired_once = False
            return httpx.Response(401)
        if self.admin_status != 200:
            return httpx.Response(self.admin_status)
        if path.startswith("/clients"):
            return httpx.Response(
                200, json=[{"id": CLIENT_UUID, "clientId": settings.OIDC_CLIENT_ID}]
            )
        parts = path.strip("/").split("/")
        person = self.people.get(parts[1]) if len(parts) > 1 else None
        if person is None:
            return httpx.Response(404)
        if len(parts) == 2:
            return httpx.Response(200, json={"id": person.sub, "enabled": person.enabled})
        if parts[2] == "groups":
            return httpx.Response(200, json=[{"path": g} for g in person.groups])
        return httpx.Response(200, json=[{"name": r} for r in person.roles])
