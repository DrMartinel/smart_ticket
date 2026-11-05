"""The company directory: IT creates people's Keycloak accounts before HR's import links them."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class DirectoryAccount:
    """A company sign-in account as IT creates it."""

    username: str
    first_name: str
    last_name: str
    password: str

    @property
    def email(self) -> str:
        return f"{self.username}@congty.vn"


class Directory:
    """Keycloak's admin API, signed in as the bootstrap admin of the local realm."""

    def __init__(self, server: str, realm: str, admin_user: str, admin_password: str) -> None:
        self.server = server.rstrip("/")
        self.realm = realm
        token = httpx.post(
            f"{self.server}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": admin_user,
                "password": admin_password,
            },
            timeout=15.0,
        )
        token.raise_for_status()
        self.http = httpx.Client(
            base_url=f"{self.server}/admin/realms/{realm}",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            timeout=15.0,
        )

    def exists(self, username: str) -> bool:
        found = self.http.get("/users", params={"username": username, "exact": "true"})
        found.raise_for_status()
        return bool(found.json())

    def ensure(self, account: DirectoryAccount) -> bool:
        """Creates the account with a set password; returns False when it already existed."""
        if self.exists(account.username):
            return False
        created = self.http.post(
            "/users",
            json={
                "username": account.username,
                "email": account.email,
                "firstName": account.first_name,
                "lastName": account.last_name,
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
                "credentials": [
                    {"type": "password", "value": account.password, "temporary": False}
                ],
            },
        )
        created.raise_for_status()
        return True
