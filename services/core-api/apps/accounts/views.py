"""
Account endpoints, and sign-in (ADR-0029): `/api/auth/login` and
`/api/auth/refresh` answer with an access token and set the rotating refresh
token as an httpOnly cookie, one per frontend (`X-Auth-Client`).
"""

import uuid
from typing import Literal, cast

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from ninja import Form, Header, Router, Status

from apps.accounts.models import AuthClient, RefreshSession, User
from apps.accounts.utils.catalog import Permission
from apps.accounts.permissions import AuthedRequest, SessionAuth, require
from apps.accounts.request_schema import LoginIn, OidcExchangeIn, RightsIn
from apps.accounts.response_schema import (
    OidcConfigOut,
    AccountOut,
    RefusedOut,
    SessionOut,
    SignInOut,
    StaffOut,
    UserOut,
)
from apps.accounts.utils import IssuedSession, Requester, SessionRefused, sessions
from apps.accounts.utils.rights import account_rights
from apps.accounts.utils.oidc import oidc_sign_in

router = Router(tags=["accounts"])
auth_router = Router(tags=["auth"])

# The refresh cookie is sent only to the sign-in endpoints.
COOKIE_PATH = "/api/auth/"


@router.get("/me", auth=SessionAuth(), response=UserOut)
@require(Permission.SELF_PROFILE)
def me(request: AuthedRequest) -> User:
    return request.auth


@router.get("/staff", auth=SessionAuth(), response=list[StaffOut])
@require(Permission.ACCESS_PEOPLE_READ)
def staff(request: AuthedRequest) -> QuerySet[User]:
    return User.objects.support_staff().order_by("username")


@router.get("/people", auth=SessionAuth(), response=list[AccountOut])
@require(Permission.ACCESS_PEOPLE_READ)
def people(request: AuthedRequest) -> QuerySet[User]:
    return User.objects.prefetch_related("assignments__role", "team_memberships__team").order_by(
        "username"
    )


@router.put("/people/{username}/rights", auth=SessionAuth(), response=AccountOut)
@require(Permission.ACCESS_GRANT)
def set_rights(request: AuthedRequest, username: str, payload: RightsIn) -> User:
    account_rights.assign(
        request.auth, username, payload.role, set(payload.capabilities), payload.reason
    )
    return User.objects.prefetch_related("assignments__role", "team_memberships__team").get(
        username=username
    )


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


@auth_router.get("/oidc/config", auth=None, response=OidcConfigOut)
def oidc_config(request: HttpRequest) -> dict[str, str]:
    return oidc_sign_in.config()


@auth_router.post("/oidc/exchange", auth=None, response=SessionOut)
def oidc_exchange(
    request: HttpRequest,
    response: HttpResponse,
    payload: OidcExchangeIn,
    x_auth_client: AuthClient = Header(...),
) -> IssuedSession:
    issued = oidc_sign_in.exchange(
        code=payload.code,
        verifier=payload.code_verifier,
        nonce=payload.nonce,
        redirect_uri=payload.redirect_uri,
        client=x_auth_client,
        requester=requester(request),
    )
    set_refresh_cookie(response, x_auth_client, issued)
    return issued


@auth_router.post("/oidc/backchannel-logout", auth=None, response={200: None})
def oidc_backchannel_logout(request: HttpRequest, logout_token: Form[str]) -> Status[None]:
    oidc_sign_in.backchannel_logout(logout_token)
    return Status(200, None)


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
@require(Permission.SELF_SESSIONS)
def list_sign_ins(request: AuthedRequest) -> list[RefreshSession]:
    return sessions.live(request.auth)


@auth_router.delete("/sessions/{family}", auth=SessionAuth(), response={204: None})
@require(Permission.SELF_SESSIONS)
def end_sign_in(request: AuthedRequest, family: uuid.UUID) -> Status[None]:
    sessions.end(request.auth, family)
    return Status(204, None)


@auth_router.post("/logout-everywhere", auth=SessionAuth(), response={204: None})
@require(Permission.SELF_SESSIONS)
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
