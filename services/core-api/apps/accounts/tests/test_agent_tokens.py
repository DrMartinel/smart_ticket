"""An agent turn's token acts as its user and is refused on every route (F15 PR 1, ADR-0046)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.test import RequestFactory
from ninja_jwt.exceptions import AuthenticationFailed
from ninja_jwt.tokens import AccessToken

from apps.accounts.models import AuthClient
from apps.accounts.permissions import (
    AccessError,
    AccessRefusal,
    Caller,
    SessionAuth,
    gate_of,
    require,
)
from apps.accounts.testing import agent_token_for, api_client_for
from apps.accounts.utils import Requester, SessionRefused, sessions
from apps.accounts.utils.catalog import Permission
from apps.audit.models import AuditLog
from apps.core.testing import api_client_with
from config.urls import api
from django.utils import timezone

pytestmark = pytest.mark.django_db

# Sign-in, refresh, sign-out and signed callbacks: no bearer token is read on them.
UNGATED = {
    "POST /api/auth/login",
    "GET /api/auth/oidc/config",
    "POST /api/auth/oidc/exchange",
    "POST /api/auth/oidc/backchannel-logout",
    "POST /api/auth/refresh",
    "POST /api/auth/logout",
    "POST /api/itsm/executions/{execution_id}/callback",
    "POST /api/lifecycle/action-runs/{run_id}/callback",
}


def operations():
    for prefix, router in api._routers:
        for path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                for method in operation.methods:
                    yield f"{method} /api{prefix.rstrip('/')}{path}", operation


def test_an_agent_token_carries_its_user_sign_in_conversation_and_turn(employee_user):
    conversation, turn = uuid.uuid4(), uuid.uuid4()

    token = AccessToken(agent_token_for(employee_user, conversation=conversation, turn=turn))

    assert token["token_type"] == "access"
    assert str(token["user_id"]) == str(employee_user.id)
    assert token["act"] == "agent"
    assert token["agc"] == str(conversation)
    assert token["agt"] == str(turn)
    assert token["sid"]
    assert token["exp"] - token["iat"] <= settings.THRESHOLDS.agent.token_ttl_seconds


def test_an_agent_token_never_outlives_its_sign_in(employee_user):
    token = AccessToken(agent_token_for(employee_user, family_hours=1 / 60))

    assert token["exp"] <= (timezone.now() + timedelta(minutes=1)).timestamp() + 1


def test_no_agent_token_is_minted_for_an_ended_sign_in(employee_user):
    now = timezone.now()
    family = uuid.uuid4()
    sessions.new_token(
        employee_user,
        AuthClient.CHAT,
        family,
        now=now,
        family_ends=now + timedelta(hours=1),
        requester=Requester(user_agent="tests", ip_address=None),
    )
    sessions.revoke_family(family, "logout")

    with pytest.raises(SessionRefused):
        sessions.issue_for_agent(
            employee_user, family, conversation=uuid.uuid4(), turn=uuid.uuid4()
        )


def test_every_gated_route_refuses_an_agent_token_even_with_the_permission(
    employee_user, monkeypatch
):
    monkeypatch.setattr(Caller, "holds", lambda self, permission: True)
    token = agent_token_for(employee_user)
    ungated, refused = set(), set()

    for key, operation in operations():
        if gate_of(operation.view_func) is None:
            ungated.add(key)
            assert not operation.auth_callbacks, key
            continue
        request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
        for callback in operation.auth_callbacks:
            with pytest.raises(AccessError) as refused_with:
                callback(request)
            assert refused_with.value.code is AccessRefusal.AGENT_NOT_ALLOWED, key
        refused.add(key)

    assert ungated == UNGATED
    assert len(refused) == len(list(operations())) - len(UNGATED)


def test_require_refuses_an_agent_when_the_handler_is_called_directly(employee_user):
    token = agent_token_for(employee_user)
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
    setattr(request, "auth", SessionAuth()(request))
    handler = require(Permission.SELF_PROFILE)(lambda request: "ran")

    with pytest.raises(AccessError) as refused:
        handler(request)

    assert refused.value.code is AccessRefusal.AGENT_NOT_ALLOWED


def test_an_agent_token_is_refused_where_its_user_is_refused(employee_user):
    own = api_client_for(employee_user, AuthClient.CHAT).get(
        f"/api/tickets/board?workflow={uuid.uuid4()}"
    )
    agent = api_client_with(agent_token_for(employee_user)).get(
        f"/api/tickets/board?workflow={uuid.uuid4()}"
    )

    assert own.status_code == agent.status_code == 403
    assert agent.json() == own.json()
    assert agent.json()["code"] == "permission_missing"


def test_the_person_gets_in_and_their_agent_is_refused_and_audited(technician_user):
    turn = uuid.uuid4()

    own = api_client_for(technician_user).get("/api/accounts/me")
    agent = api_client_with(agent_token_for(technician_user, turn=turn)).get("/api/accounts/me")

    assert own.status_code == 200
    assert agent.status_code == 403
    assert agent.json()["code"] == "agent_not_allowed"
    row = AuditLog.objects.get(event="agent_call_refused")
    assert row.actor_id == technician_user.id
    assert row.payload["via"] == "agent"
    assert row.payload["agent_turn_id"] == str(turn)
    assert row.payload["permission"] == Permission.SELF_PROFILE.value


def test_a_refused_permission_is_audited_as_via_the_agent(employee_user):
    turn = uuid.uuid4()

    api_client_with(agent_token_for(employee_user, turn=turn)).get(
        f"/api/tickets/board?workflow={uuid.uuid4()}"
    )

    row = AuditLog.objects.get(event="access_denied")
    assert row.payload["via"] == "agent"
    assert row.payload["agent_turn_id"] == str(turn)


def test_an_agent_token_dies_with_the_sign_in(employee_user):
    token = agent_token_for(employee_user)
    sessions.revoke_user(employee_user, "logout")

    assert api_client_with(token).get("/api/accounts/me").status_code == 401


@pytest.mark.parametrize(
    "claims",
    [{"act": "robot"}, {"act": "agent", "agc": str(uuid.uuid4())}, {"act": "agent", "agt": "x"}],
)
def test_a_token_with_an_actor_core_api_does_not_issue_is_refused(employee_user, claims):
    token = AccessToken(agent_token_for(employee_user))
    for claim in ("act", "agc", "agt"):
        del token[claim]
    for claim, value in claims.items():
        token[claim] = value

    with pytest.raises(AuthenticationFailed):
        SessionAuth().jwt_authenticate(RequestFactory().get("/"), str(token))
