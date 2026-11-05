"""One persona's signed-in session: Keycloak sign-in, token refresh and API calls, as a browser makes them."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

FORM_ACTION = re.compile(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', re.S)
ANY_FORM_ACTION = re.compile(r'<form[^>]+action="([^"]+)"', re.S)
ERROR_TEXT = re.compile(
    r'class="[^"]*(?:kc-feedback-text|alert-error|pf-m-danger)[^"]*"[^>]*>\s*([^<]+)', re.S
)


class ApiError(Exception):
    """A response the persona did not expect."""

    def __init__(self, method: str, path: str, status: int, body: Any) -> None:
        super().__init__(f"{method} {path} → {status}: {body}")
        self.status = status
        self.body = body

    @property
    def code(self) -> str:
        """The refusal code the API sent, if any."""
        if isinstance(self.body, dict):
            return str(self.body.get("code") or self.body.get("detail") or "")
        return str(self.body)


@dataclass
class CallLog:
    """Every request the simulation made, in order."""

    path: str
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


@dataclass(frozen=True)
class Endpoints:
    """Where the stack listens."""

    api: str
    admin_origin: str
    chat_origin: str


class Session:
    """A persona signed in to one frontend (admin console or chat) through the company sign-in."""

    def __init__(
        self, persona: str, password: str, client: str, ends: Endpoints, log: CallLog
    ) -> None:
        self.persona = persona
        self.password = password
        self.client = client
        self.ends = ends
        self.log = log
        self.origin = ends.admin_origin if client == "admin" else ends.chat_origin
        self.http = httpx.Client(
            base_url=ends.api,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"X-Auth-Client": client, "Origin": self.origin},
        )
        self.access: str | None = None
        self.expires_at = 0.0
        self.me: dict[str, Any] = {}

    # ── sign-in ──

    def sign_in(self) -> dict[str, Any]:
        """Signs in through Keycloak's login page and exchanges the code, like the callback page."""
        config = self.http.get("/api/auth/oidc/config").json()
        verifier = secrets.token_urlsafe(48)
        state, nonce = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        redirect_uri = f"{self.origin}/auth/callback"
        query = urlencode(
            {
                "client_id": config["client_id"],
                "response_type": "code",
                "scope": config["scopes"],
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        with httpx.Client(timeout=15.0, follow_redirects=False) as idp:
            idp.event_hooks["response"] = [lambda _: self.treat_localhost_as_secure(idp)]
            page = idp.get(f"{config['authorize_url']}?{query}")
            code = self.code_from(page, redirect_uri) or self.submit_login(idp, page, redirect_uri)
        body = {
            "code": code,
            "code_verifier": verifier,
            "nonce": nonce,
            "redirect_uri": redirect_uri,
        }
        issued = self.call("POST", "/api/auth/oidc/exchange", json=body, auth=False)
        self.keep(issued)
        self.me = self.get("/api/accounts/me")
        return self.me

    def submit_login(self, idp: httpx.Client, page: httpx.Response, redirect_uri: str) -> str:
        """Fills Keycloak's username and password form, then any profile step it asks for."""
        response = self.post_form(
            idp, page, {"username": self.persona, "password": self.password, "credentialId": ""}
        )
        for _ in range(3):
            code = self.code_from(response, redirect_uri)
            if code:
                return code
            response = self.post_form(idp, response, {})
        raise RuntimeError(
            f"{self.persona}: Keycloak did not return a code ({self.idp_error(response)})"
        )

    def post_form(
        self, idp: httpx.Client, page: httpx.Response, fields: dict[str, str]
    ) -> httpx.Response:
        match = FORM_ACTION.search(page.text) or ANY_FORM_ACTION.search(page.text)
        if not match:
            raise RuntimeError(f"{self.persona}: no sign-in form ({page.status_code})")
        return idp.post(html.unescape(match.group(1)), data=fields)

    @staticmethod
    def treat_localhost_as_secure(idp: httpx.Client) -> None:
        """Lets Keycloak's Secure cookies go back over http://localhost, as a browser sends them."""
        for cookie in idp.cookies.jar:
            cookie.secure = False

    @staticmethod
    def code_from(response: httpx.Response, redirect_uri: str) -> str | None:
        location = response.headers.get("location", "")
        if response.status_code in (302, 303) and location.startswith(redirect_uri):
            return parse_qs(urlparse(location).query).get("code", [None])[0]
        return None

    @staticmethod
    def idp_error(response: httpx.Response) -> str:
        match = ERROR_TEXT.search(response.text)
        return match.group(1).strip() if match else f"status {response.status_code}"

    def keep(self, issued: dict[str, Any]) -> None:
        self.access = issued["access"]
        expires = datetime.fromisoformat(issued["access_expires_at"].replace("Z", "+00:00"))
        left = (expires - datetime.now(UTC)).total_seconds()
        self.expires_at = time.monotonic() + max(15.0, left - 30)

    def refresh(self) -> None:
        """Swaps the refresh cookie for a new access token, as the frontends do before expiry; when the
        sign-in has ended (an access change ends it), signs in again as the login page would make them."""
        try:
            issued = self.call("POST", "/api/auth/refresh", auth=False)
        except ApiError as e:
            if e.status != 401:
                raise
            self.http.cookies.clear()
            self.sign_in()
            return
        self.keep(issued)

    def sign_out(self) -> None:
        if self.access:
            self.call("POST", "/api/auth/logout", ok=(200, 204, 401))
        self.access = None

    # ── calls ──

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, body: Any | None = None, **kw: Any) -> Any:
        return self.call("POST", path, json=body if body is not None else {}, **kw)

    def put(self, path: str, body: Any, **kw: Any) -> Any:
        return self.call("PUT", path, json=body, **kw)

    def patch(self, path: str, body: Any, **kw: Any) -> Any:
        return self.call("PATCH", path, json=body, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.call("DELETE", path, **kw)

    def call(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        ok: tuple[int, ...] = (200, 201, 204),
        retry: bool = True,
        **kw: Any,
    ) -> Any:
        """One request; refreshes the token once on a 401, and raises ApiError on any status not in `ok`."""
        if auth and (self.access is None or time.monotonic() > self.expires_at):
            self.refresh()
        headers = {"Authorization": f"Bearer {self.access}"} if auth else {}
        started = time.monotonic()
        response = self.http.request(method, path, headers=headers, **kw)
        if response.status_code == 401 and auth and retry:
            self.refresh()
            return self.call(method, path, auth=auth, ok=ok, retry=False, **kw)
        body: Any
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = response.text[:500]
        self.log.add(
            {
                "at": time.time(),
                "persona": self.persona,
                "client": self.client,
                "method": method,
                "path": path,
                "status": response.status_code,
                "ms": round((time.monotonic() - started) * 1000),
                "error": None if response.status_code in ok else body,
            }
        )
        if response.status_code not in ok:
            raise ApiError(method, path, response.status_code, body)
        return body
