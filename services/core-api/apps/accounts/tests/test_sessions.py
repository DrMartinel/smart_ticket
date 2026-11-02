"""Sign-in over HTTP: the access token, the rotating refresh cookie, reuse detection and sign-out."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from apps.accounts.models import RefreshSession
from apps.audit.models import AuditLog
from apps.notifications.models import Message
from apps.core.testing import api_client_with

pytestmark = pytest.mark.django_db

COOKIE = "st_refresh_admin"


def login(client: Client, username: str = "glass", password: str = "x", frontend: str = "admin"):
    return client.post(
        "/api/auth/login",
        {"username": username, "password": password},
        content_type="application/json",
        HTTP_X_AUTH_CLIENT=frontend,
    )


def refresh(client: Client, frontend: str = "admin"):
    return client.post(
        "/api/auth/refresh", content_type="application/json", HTTP_X_AUTH_CLIENT=frontend
    )


def me(access: str) -> int:
    return api_client_with(access).get("/api/accounts/me").status_code


def test_login_returns_an_access_token_and_sets_an_httponly_refresh_cookie(glass_user):
    client = Client()

    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "glass"
    assert me(body["access"]) == 200
    cookie = response.cookies[COOKIE]
    assert cookie["httponly"]
    assert cookie["path"] == "/api/auth/"
    assert cookie["samesite"] == "Lax"
    assert "refresh" not in body


def test_a_wrong_password_sets_no_cookie_and_is_audited(glass_user):
    response = login(Client(), password="wrong")

    assert response.status_code == 401
    assert COOKIE not in response.cookies
    assert AuditLog.objects.filter(event="auth_login_failed").exists()


def test_a_request_without_the_client_header_is_refused(glass_user):
    response = Client().post(
        "/api/auth/login",
        {"username": "glass", "password": "x"},
        content_type="application/json",
    )

    assert response.status_code == 422


def test_refresh_rotates_the_cookie_and_issues_a_working_access_token(glass_user):
    client = Client()
    first = login(client).cookies[COOKIE].value

    response = refresh(client)

    assert response.status_code == 200
    assert response.cookies[COOKIE].value != first
    assert me(response.json()["access"]) == 200


def test_a_reused_refresh_token_ends_the_whole_sign_in(glass_user, security_user, settings):
    settings.AUTH_REFRESH_REUSE_GRACE_SEC = 0
    client = Client()
    first = login(client).cookies[COOKIE].value
    access = refresh(client).json()["access"]

    thief = Client()
    thief.cookies[COOKIE] = first
    stolen = refresh(thief)

    assert stolen.status_code == 401
    assert refresh(client).status_code == 401
    assert me(access) == 401
    assert AuditLog.objects.filter(
        event="security_alert", payload__reason="refresh_token_reused"
    ).exists()
    assert Message.objects.filter(
        user=security_user, event="security.alert", subject__contains="refresh_token_reused"
    ).exists()


def test_two_tabs_refreshing_at_once_both_get_an_access_token(glass_user):
    client = Client()
    first = login(client).cookies[COOKIE].value
    refresh(client)

    other_tab = Client()
    other_tab.cookies[COOKIE] = first
    response = refresh(other_tab)

    assert response.status_code == 200
    assert COOKIE not in response.cookies
    assert me(response.json()["access"]) == 200


def test_logout_revokes_the_refresh_cookie_and_the_access_token_at_once(glass_user):
    client = Client()
    signed_in = login(client)
    access, raw = signed_in.json()["access"], signed_in.cookies[COOKIE].value

    response = client.post(
        "/api/auth/logout", content_type="application/json", HTTP_X_AUTH_CLIENT="admin"
    )

    assert response.status_code == 204
    assert response.cookies[COOKIE].value == ""
    assert me(access) == 401
    client.cookies[COOKIE] = raw
    assert refresh(client).status_code == 401


def test_an_access_token_from_no_sign_in_is_refused(glass_user):
    bare = AccessToken.for_user(glass_user)  # type: ignore[misc]

    assert me(str(bare)) == 401


def test_each_frontend_keeps_its_own_cookie(glass_user):
    client = Client()
    login(client)

    response = refresh(client, frontend="chat")

    assert response.status_code == 401


def test_an_idle_refresh_token_expires(glass_user):
    client = Client()
    login(client)
    RefreshSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

    assert refresh(client).status_code == 401


def test_a_sign_in_cannot_outlive_its_maximum_age(glass_user):
    client = Client()
    login(client)
    RefreshSession.objects.update(family_expires_at=timezone.now() - timedelta(seconds=1))

    assert refresh(client).status_code == 401


def test_a_deactivated_user_cannot_refresh(glass_user):
    client = Client()
    access = login(client).json()["access"]
    glass_user.is_active = False
    glass_user.save()

    assert refresh(client).status_code == 401
    assert me(access) == 401


def test_a_user_lists_and_ends_their_sign_ins(glass_user):
    laptop, phone = Client(), Client()
    access = login(laptop).json()["access"]
    phone_access = login(phone, frontend="chat").json()["access"]
    api = api_client_with(access)

    listed = api.get("/api/auth/sessions").json()
    assert sorted(s["client"] for s in listed) == ["admin", "chat"]

    chat = next(s for s in listed if s["client"] == "chat")
    assert api.delete(f"/api/auth/sessions/{chat['family']}").status_code == 204
    assert me(phone_access) == 401
    assert me(access) == 200


def test_logout_everywhere_ends_every_sign_in(glass_user):
    first = login(Client()).json()["access"]
    second = login(Client()).json()["access"]

    response = api_client_with(first).post("/api/auth/logout-everywhere")

    assert response.status_code == 204
    assert me(first) == 401
    assert me(second) == 401


def test_a_user_cannot_end_someone_elses_sign_in(glass_user, second_glass_user):
    victim = login(Client(), username="glass2").json()["access"]
    family = RefreshSession.objects.get(user=second_glass_user).family
    attacker = login(Client()).json()["access"]

    api_client_with(attacker).delete(f"/api/auth/sessions/{family}")

    assert me(victim) == 200


def test_the_frontends_may_send_credentials_and_the_client_header(settings):
    origin = settings.CORS_ALLOWED_ORIGINS[0]

    response = Client().options(
        "/api/auth/refresh",
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-auth-client",
    )

    assert response["access-control-allow-credentials"] == "true"
    assert "x-auth-client" in response["access-control-allow-headers"]


def test_the_refresh_token_is_stored_only_as_a_hash(glass_user):
    raw = login(Client()).cookies[COOKIE].value

    stored = RefreshSession.objects.get().token_hash
    assert raw not in stored
    assert len(stored) == 64
