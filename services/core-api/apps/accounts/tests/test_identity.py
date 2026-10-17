"""Signing in through Keycloak, rights from its claims, and losing access when it says so (F13)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from django.db import IntegrityError, transaction
from django.test import Client

from apps.accounts.models import IdentitySyncRun, RefreshSession, User
from apps.accounts.tests.fake_keycloak import FakeKeycloak, Person, new_key
from apps.accounts.utils.identity_sync import IdentitySync
from apps.accounts.utils.oidc import Identities, Keycloak, oidc_sign_in
from apps.audit.models import AuditLog
from apps.core.testing import api_client_with
from apps.teams.models import Team

pytestmark = pytest.mark.django_db

CALLBACK = "http://localhost:3001/auth/callback"
VERIFIER = "v" * 43


@pytest.fixture
def realm(monkeypatch) -> FakeKeycloak:
    fake = FakeKeycloak()
    keycloak = Keycloak()
    monkeypatch.setattr(
        keycloak,
        "http",
        # httpx._client.Client: the autouse ai-engine stub replaces httpx.Client.
        lambda: httpx._client.Client(transport=httpx.MockTransport(fake.handle)),
    )
    monkeypatch.setattr(oidc_sign_in, "keycloak", keycloak)
    fake.keycloak = keycloak  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def teams() -> None:
    for slug in ("network", "hardware", "access"):
        Team.objects.create(slug=slug, name=slug.title())


def exchange(code: str, *, client: str = "chat", nonce: str = "nonce-1", **body: Any):
    payload = {"code": code, "code_verifier": VERIFIER, "nonce": nonce, "redirect_uri": CALLBACK}
    return Client().post(
        "/api/auth/oidc/exchange",
        {**payload, **body},
        content_type="application/json",
        headers={"X-Auth-Client": client},
    )


def sign_in(realm: FakeKeycloak, person: Person, client: str = "admin"):
    return exchange(realm.code_for(person), client=client)


def me(access: str):
    return api_client_with(access).get("/api/accounts/me")


def events(name: str) -> list[AuditLog]:
    return list(AuditLog.objects.filter(event=name))


def sync(realm: FakeKeycloak) -> IdentitySyncRun | None:
    return IdentitySync(realm.keycloak, Identities()).run()  # type: ignore[attr-defined]


def lan_person(**overrides: Any) -> Person:
    """Nguyễn Thị Lan, an employee in Finance."""
    fields: dict[str, Any] = {
        "username": "lan.nt",
        "roles": ["employee"],
        "groups": ["/finance"],
        "name": "Nguyễn Thị Lan",
    }
    return Person(**{**fields, **overrides})


class TestSignIn:
    def test_first_sign_in_creates_the_user(self, realm):
        """AC-F13-01."""
        lan = realm.add(lan_person(sub="3f9b2c41-7d0e-4a8e-9c55-1b2e8f6d0a12"))

        response = sign_in(realm, lan, client="chat")

        assert response.status_code == 200
        user = User.objects.get(external_id=lan.sub)
        assert (user.username, user.role, user.auth_source) == ("lan.nt", "employee", "oidc")
        assert not user.has_usable_password()
        assert "st_refresh_chat" in response.cookies
        assert len(events("identity_provisioned")) == 1
        (login,) = events("auth_login")
        assert login.payload["method"] == "oidc"
        assert me(response.json()["access"]).status_code == 200

    def test_rights_come_from_keycloak(self, realm, teams):
        """AC-F13-02."""
        duc = realm.add(
            Person(
                username="duc.tm",
                roles=["technician", "incident_manager"],
                groups=["/it/network/lead", "/it/hardware"],
            )
        )

        body = me(sign_in(realm, duc).json()["access"]).json()

        assert body["role"] == "technician"
        assert body["capabilities"] == ["incident_manager"]
        assert body["teams"] == [
            {"team": "hardware", "role": "member"},
            {"team": "network", "role": "lead"},
        ]
        assert body["auth_source"] == "oidc"

    def test_no_client_role_no_access(self, realm):
        """AC-F13-03."""
        nobody = realm.add(Person(username="no.role", roles=[]))

        response = sign_in(realm, nobody)

        assert response.status_code == 403
        assert response.json()["code"] == "no_access"
        assert not User.objects.filter(username="no.role").exists()

    def test_two_primary_roles_refused(self, realm):
        """AC-F13-04."""
        both = realm.add(Person(username="two.roles", roles=["technician", "manager"]))

        response = sign_in(realm, both)

        assert response.status_code == 403
        assert response.json()["code"] == "ambiguous_role"
        assert len(events("security_alert")) == 1
        assert not User.objects.filter(username="two.roles").exists()

    def test_a_forged_id_token_is_refused(self, realm, monkeypatch):
        """AC-F13-09: signed by a key Keycloak never published."""
        lan = realm.add(lan_person())
        forger = new_key()
        monkeypatch.setattr(
            realm,
            "id_token",
            lambda person, nonce, **kw: realm.sign(
                {
                    "iss": realm.base,
                    "aud": "smart-ticket",
                    "sub": person.sub,
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 300,
                    "nonce": nonce,
                },
                key=forger,
            ),
        )

        response = sign_in(realm, lan)

        assert response.status_code == 401
        assert response.json()["code"] == "oidc_token_invalid"
        assert not User.objects.exists()

    @pytest.mark.parametrize(
        "override",
        [
            {"aud": "another-client"},
            {"iss": "https://evil.example.com/realms/x"},
            {"exp": int(time.time()) - 120},
        ],
        ids=["audience", "issuer", "expired"],
    )
    def test_a_token_for_someone_else_is_refused(self, realm, monkeypatch, override):
        """FR-F13-002."""
        lan = realm.add(lan_person())
        original = realm.id_token
        monkeypatch.setattr(realm, "id_token", lambda p, n: original(p, n, **override))

        assert sign_in(realm, lan).json()["code"] == "oidc_token_invalid"

    def test_a_nonce_mismatch_is_refused(self, realm):
        lan = realm.add(lan_person())

        response = exchange(realm.code_for(lan, nonce="the-real-one"), nonce="replayed")

        assert response.json()["code"] == "oidc_token_invalid"

    def test_an_unknown_redirect_uri_is_refused(self, realm):
        lan = realm.add(lan_person())

        response = exchange(realm.code_for(lan), redirect_uri="https://evil.example.com/cb")

        assert response.status_code == 400
        assert response.json()["code"] == "redirect_uri_not_allowed"

    def test_a_used_code_is_refused(self, realm):
        lan = realm.add(lan_person())
        code = realm.code_for(lan)

        assert exchange(code).status_code == 200
        assert exchange(code).json()["code"] == "oidc_token_invalid"

    def test_a_local_user_with_the_same_verified_email_is_linked(self, realm, django_user_model):
        """UC-F13-01 5a."""
        local = django_user_model.objects.create_user(
            username="lan", email="lan.nt@congty.vn", password="x"
        )
        lan = realm.add(lan_person())

        sign_in(realm, lan)

        local.refresh_from_db()
        assert (local.external_id, local.auth_source) == (lan.sub, "oidc")
        assert len(events("identity_linked")) == 1
        assert User.objects.count() == 1

    def test_an_unverified_email_is_not_linked(self, realm, django_user_model):
        django_user_model.objects.create_user(
            username="lan", email="lan.nt@congty.vn", password="x"
        )
        lan = realm.add(lan_person(email_verified=False))

        sign_in(realm, lan)

        assert User.objects.filter(external_id=lan.sub).get().username == "lan.nt"
        assert User.objects.count() == 2

    def test_a_taken_username_gets_a_suffix(self, realm, django_user_model):
        """UC-F13-02 1a."""
        django_user_model.objects.create_user(username="lan.nt", email="other@x.vn", password="x")
        lan = realm.add(lan_person(sub="3f9b2c41-7d0e-4a8e-9c55-1b2e8f6d0a12"))

        sign_in(realm, lan)

        assert User.objects.get(external_id=lan.sub).username == "lan.nt-3f9b"

    def test_unknown_roles_and_groups_are_ignored_and_logged(self, realm, teams):
        """BR-F13-03."""
        lan = realm.add(
            Person(
                username="lan.nt", roles=["employee", "astronaut"], groups=["/finance", "/it/space"]
            )
        )

        response = sign_in(realm, lan)

        assert response.status_code == 200
        assert me(response.json()["access"]).json()["teams"] == []
        (ignored,) = events("identity_claims_ignored")
        assert ignored.payload["ignored"] == ["astronaut", "/finance"]

    def test_the_sign_in_config_names_the_authorize_url(self, realm):
        body = Client().get("/api/auth/oidc/config").json()

        assert body["authorize_url"].endswith("/protocol/openid-connect/auth")
        assert body["client_id"] == "smart-ticket"


class TestKeycloakDown:
    def test_keycloak_down_does_not_end_existing_sessions(self, realm):
        """AC-F13-06."""
        lan = realm.add(lan_person())
        client = Client()
        signed_in = client.post(
            "/api/auth/oidc/exchange",
            {
                "code": realm.code_for(lan),
                "code_verifier": VERIFIER,
                "nonce": "nonce-1",
                "redirect_uri": CALLBACK,
            },
            content_type="application/json",
            headers={"X-Auth-Client": "chat"},
        )
        assert signed_in.status_code == 200
        realm.down = True

        refreshed = client.post("/api/auth/refresh", headers={"X-Auth-Client": "chat"})
        newcomer = Client().get("/api/auth/oidc/config")

        assert refreshed.status_code == 200
        assert newcomer.status_code == 502
        assert newcomer.json()["code"] == "idp_unavailable"


class TestLocalSignIn:
    def test_local_login_is_closed_to_normal_users(self, django_user_model):
        """AC-F13-07."""
        django_user_model.objects.create_user(username="duc.tm", password="x", role="technician")

        response = Client().post(
            "/api/auth/login",
            {"username": "duc.tm", "password": "x"},
            content_type="application/json",
            headers={"X-Auth-Client": "admin"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "local_login_disabled"
        assert not RefreshSession.objects.exists()

    def test_break_glass_use_alerts_security(self, glass_user):
        """AC-F13-08 (the audit row; the notice to security is F4's)."""
        response = Client().post(
            "/api/auth/login",
            {"username": "glass", "password": "x"},
            content_type="application/json",
            headers={"X-Auth-Client": "admin"},
        )

        assert response.status_code == 200
        (alert,) = events("security_alert")
        assert alert.payload["reason"] == "break_glass_used"
        assert events("auth_login")[0].payload["method"] == "local"

    def test_break_glass_locks_after_repeated_failures(self, glass_user, settings):
        """FR-F13-009."""
        attempts = settings.THRESHOLDS.identity.local_max_failures
        post = lambda password: Client().post(  # noqa: E731
            "/api/auth/login",
            {"username": "glass", "password": password},
            content_type="application/json",
            headers={"X-Auth-Client": "admin"},
        )

        statuses = [post("wrong").status_code for _ in range(attempts)]
        locked = post("x")

        assert statuses == [401] * attempts
        assert locked.status_code == 423
        assert locked.json()["code"] == "account_locked"

    def test_break_glass_only_manager(self, django_user_model):
        """BR-F13-06: the database refuses a break-glass flag on any other role."""
        with pytest.raises(IntegrityError), transaction.atomic():
            django_user_model.objects.create_user(
                username="x", password="x", role="technician", is_break_glass=True
            )


class TestLeavers:
    def test_backchannel_logout_revokes_all_families(self, realm):
        """AC-F13-05, back-channel delivered."""
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        first = sign_in(realm, duc).json()["access"]
        second = sign_in(realm, duc, client="chat").json()["access"]

        response = Client().post(
            "/api/auth/oidc/backchannel-logout", {"logout_token": realm.logout_token(duc)}
        )

        assert response.status_code == 200
        assert me(first).status_code == me(second).status_code == 401
        assert len(events("auth_backchannel_logout")) == 1

    def test_a_logout_token_that_is_not_one_is_refused(self, realm):
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        access = sign_in(realm, duc).json()["access"]

        response = Client().post(
            "/api/auth/oidc/backchannel-logout",
            {"logout_token": realm.logout_token(duc, events={})},
        )

        assert response.status_code == 400
        assert response.json()["code"] == "logout_token_invalid"
        assert me(access).status_code == 200

    def test_sync_ends_a_disabled_users_sessions(self, realm):
        """AC-F13-05, back-channel not delivered: the next sync ends it."""
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        access = sign_in(realm, duc).json()["access"]
        duc.enabled = False

        run = sync(realm)

        assert run is not None and run.ok and run.changed == 1
        assert me(access).status_code == 401
        assert User.objects.get(external_id=duc.sub).is_active is False
        assert events("identity_deactivated")[0].payload["reason"] == "disabled_in_keycloak"

    def test_a_returning_user_is_reactivated(self, realm):
        """UC-F13 state: inactive → active on the next sign-in with access."""
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        sign_in(realm, duc)
        duc.enabled = False
        sync(realm)
        duc.enabled = True

        response = sign_in(realm, duc)

        assert response.status_code == 200
        assert User.objects.get(external_id=duc.sub).is_active is True

    def test_lost_rights_end_sessions(self, realm):
        """BR-F13-05."""
        tu = realm.add(Person(username="tu.dv", roles=["technician", "workflow_admin"]))
        access = sign_in(realm, tu).json()["access"]
        tu.roles = ["technician"]

        sync(realm)

        assert me(access).status_code == 401
        assert User.objects.get(external_id=tu.sub).capability_set() == frozenset()
        assert len(events("identity_rights_changed")) == 1

    def test_a_team_change_alone_keeps_sessions(self, realm, teams):
        mai = realm.add(Person(username="mai.bn", roles=["technician"], groups=["/it/access"]))
        access = sign_in(realm, mai).json()["access"]
        mai.groups = ["/it/access/lead"]

        sync(realm)

        assert me(access).json()["teams"] == [{"team": "access", "role": "lead"}]

    def test_failed_keycloak_read_deactivates_nobody(self, realm):
        """AC-F13-10."""
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        access = sign_in(realm, duc).json()["access"]
        duc.enabled = False
        realm.admin_status = 503

        runs = [sync(realm) for _ in range(4)]

        assert [r.ok for r in runs if r] == [False] * 4
        assert User.objects.get(external_id=duc.sub).is_active is True
        assert me(access).status_code == 200
        assert len(events("identity_sync_failed")) == 1

    def test_keycloak_unreachable_during_sync_deactivates_nobody(self, realm):
        """BR-F13-08."""
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        sign_in(realm, duc)
        realm.down = True

        run = sync(realm)

        assert run is not None and not run.ok
        assert User.objects.get(external_id=duc.sub).is_active is True

    def test_two_roles_found_by_sync_deactivate_and_alert(self, realm):
        duc = realm.add(Person(username="duc.tm", roles=["technician"]))
        sign_in(realm, duc)
        duc.roles = ["technician", "manager"]

        sync(realm)

        assert User.objects.get(external_id=duc.sub).is_active is False
        assert events("security_alert")[-1].payload["reason"] == "ambiguous_role"

    def test_a_second_sync_changes_nothing(self, realm, teams):
        """Idempotent: the second run finds nothing to do."""
        duc = realm.add(Person(username="duc.tm", roles=["technician"], groups=["/it/network"]))
        sign_in(realm, duc)

        first, second = sync(realm), sync(realm)

        assert first is not None and second is not None
        assert (first.changed, second.changed) == (0, 0)
