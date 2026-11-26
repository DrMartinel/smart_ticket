"""Keystone: tokens, federated users and the role assignments that decide a customer's projects."""

from __future__ import annotations

from cloud_sim.testing import Sim, token_body

LAN_SUBJECT = "0b6f8f2e-3c3a-4a51-9d1e-6a1f3c2b7e41"


def test_a_wrong_password_gets_no_token(sim: Sim) -> None:
    reply = sim.client.post("/identity/v3/auth/tokens", json=token_body(password="wrong"))

    assert reply.status_code == 401
    assert "X-Subject-Token" not in reply.headers


def test_a_customer_cannot_sign_in_to_the_cloud_directly(sim: Sim) -> None:
    reply = sim.client.post("/identity/v3/auth/tokens", json=token_body(user="lan.nt", password=""))

    assert reply.status_code == 401


def test_a_project_scoped_request_gets_no_token(sim: Sim) -> None:
    body = token_body()
    body["auth"]["scope"] = {"project": {"name": "saomai-prod"}}

    assert sim.client.post("/identity/v3/auth/tokens", json=body).status_code == 401


def test_every_read_needs_a_token(sim: Sim) -> None:
    for path in ("/identity/v3/users", "/compute/v2.1/servers/detail", "/network/v2.0/networks"):
        assert sim.client.get(path).status_code == 401
        assert sim.client.get(path, headers={"X-Auth-Token": "made-up"}).status_code == 401


def test_an_expired_token_is_refused(sim: Sim) -> None:
    sim.clock.advance(3601)

    assert sim.client.get("/identity/v3/projects", headers=sim.headers).status_code == 401


def test_the_token_lists_every_service(sim: Sim) -> None:
    reply = sim.client.post("/identity/v3/auth/tokens", json=token_body())

    types = {entry["type"] for entry in reply.json()["token"]["catalog"]}
    assert types == {"identity", "compute", "volumev3", "network"}


def test_a_customer_is_found_by_their_keycloak_subject(sim: Sim) -> None:
    reply = sim.client.get(
        "/identity/v3/users",
        params={"idp_id": "smart-ticket", "protocol_id": "openid", "unique_id": LAN_SUBJECT},
        headers=sim.headers,
    )

    assert [u["name"] for u in reply.json()["users"]] == ["lan.nt"]


def test_an_unknown_subject_finds_nobody(sim: Sim) -> None:
    reply = sim.client.get(
        "/identity/v3/users", params={"unique_id": "nobody"}, headers=sim.headers
    )

    assert reply.json()["users"] == []


def test_the_service_user_is_not_listed(sim: Sim) -> None:
    reply = sim.client.get("/identity/v3/users", headers=sim.headers)

    assert {u["name"] for u in reply.json()["users"]} == {"lan.nt", "minh.hbr"}


def test_a_customer_is_a_member_of_their_companys_projects_only(sim: Sim) -> None:
    user = sim.client.get(
        "/identity/v3/users", params={"unique_id": LAN_SUBJECT}, headers=sim.headers
    )
    user_id = user.json()["users"][0]["id"]

    reply = sim.client.get(
        "/identity/v3/role_assignments",
        params={"user.id": user_id, "include_names": "true"},
        headers=sim.headers,
    )

    names = {a["scope"]["project"]["name"] for a in reply.json()["role_assignments"]}
    assert names == {"saomai-prod", "saomai-staging"}


def test_an_unknown_project_is_404(sim: Sim) -> None:
    assert sim.client.get("/identity/v3/projects/nope", headers=sim.headers).status_code == 404
