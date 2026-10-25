"""
Account endpoints, and sign-in (ADR-0029): `/api/auth/login` and
`/api/auth/refresh` answer with an access token and set the rotating refresh
token as an httpOnly cookie, one per frontend (`X-Auth-Client`).
"""

import uuid
from typing import Literal, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import Header, Router, Status

from apps.accounts.models import AuthClient, RefreshSession, User
from apps.accounts.permissions import ALL_ROLES, AuthedRequest, SessionAuth, require_role
from apps.accounts.request_schema import LoginIn
from apps.accounts.response_schema import RefusedOut, SessionOut, SignInOut, UserOut
from apps.accounts.utils import IssuedSession, Requester, SessionRefused, sessions

router = Router(tags=["accounts"])
auth_router = Router(tags=["auth"])

# The refresh cookie is sent only to the sign-in endpoints.
COOKIE_PATH = "/api/auth/"


@router.get("/me", auth=SessionAuth(), response=UserOut)
@require_role(*ALL_ROLES)
def me(request: AuthedRequest) -> User:
    return request.auth


@auth_router.post("/login", auth=None, response={200: SessionOut, 401: RefusedOut})
def login(
    request: HttpRequest,
    response: HttpResponse,
    payload: LoginIn,
    x_auth_client: AuthClient = Header(...),
) -> Status[IssuedSession | RefusedOut]:
    try:
        issued = sessions.login(
            payload.username, payload.password, x_auth_client, requester(request)
        )
    except SessionRefused as e:
        return Status(401, RefusedOut(detail=str(e)))
    set_refresh_cookie(response, x_auth_client, issued)
    return Status(200, issued)


@auth_router.post("/refresh", auth=None, response={200: SessionOut, 401: RefusedOut})
def refresh(
    request: HttpRequest, response: HttpResponse, x_auth_client: AuthClient = Header(...)
) -> Status[IssuedSession | RefusedOut]:
    raw = request.COOKIES.get(cookie_name(x_auth_client))
    try:
        if not raw:
            raise SessionRefused("no refresh token")
        issued = sessions.refresh(raw, x_auth_client, requester(request))
    except SessionRefused as e:
        response.delete_cookie(cookie_name(x_auth_client), path=COOKIE_PATH)
        return Status(401, RefusedOut(detail=str(e)))
    set_refresh_cookie(response, x_auth_client, issued)
    return Status(200, issued)


@auth_router.post("/logout", auth=None, response={204: None})
def logout(
    request: HttpRequest, response: HttpResponse, x_auth_client: AuthClient = Header(...)
) -> Status[None]:
    raw = request.COOKIES.get(cookie_name(x_auth_client))
    if raw:
        sessions.logout(raw, x_auth_client)
    response.delete_cookie(cookie_name(x_auth_client), path=COOKIE_PATH)
    return Status(204, None)


@auth_router.get("/sessions", auth=SessionAuth(), response=list[SignInOut])
@require_role(*ALL_ROLES)
def list_sign_ins(request: AuthedRequest) -> list[RefreshSession]:
    return sessions.live(request.auth)


@auth_router.delete("/sessions/{family}", auth=SessionAuth(), response={204: None})
@require_role(*ALL_ROLES)
def end_sign_in(request: AuthedRequest, family: uuid.UUID) -> Status[None]:
    sessions.end(request.auth, family)
    return Status(204, None)


@auth_router.post("/logout-everywhere", auth=SessionAuth(), response={204: None})
@require_role(*ALL_ROLES)
def logout_everywhere(request: AuthedRequest, response: HttpResponse) -> Status[None]:
    sessions.end_all(request.auth)
    for client in AuthClient:
        response.delete_cookie(cookie_name(client), path=COOKIE_PATH)
    return Status(204, None)


def cookie_name(client: AuthClient) -> str:
    return f"st_refresh_{client.value}"


def set_refresh_cookie(response: HttpResponse, client: AuthClient, issued: IssuedSession) -> None:
    """Hands the browser the new refresh token, readable by no script."""
    if issued.refresh is None or issued.refresh_expires_at is None:
        return
    response.set_cookie(
        cookie_name(client),
        issued.refresh,
        expires=issued.refresh_expires_at,
        path=COOKIE_PATH,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=cast(Literal["Lax", "Strict", "None"], settings.AUTH_COOKIE_SAMESITE),
    )


def requester(request: HttpRequest) -> Requester:
    return Requester(
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        ip_address=request.META.get("REMOTE_ADDR") or None,
    )
