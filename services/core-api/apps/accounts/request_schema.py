"""Request shapes for the account endpoints."""

from __future__ import annotations

from ninja import Field, Schema


class OidcExchangeIn(Schema):
    """What the callback page sends after Keycloak redirects back (F13)."""

    code: str = Field(min_length=1, max_length=4096)
    code_verifier: str = Field(min_length=43, max_length=128)
    nonce: str = Field(min_length=1, max_length=256)
    redirect_uri: str = Field(min_length=1, max_length=500)


class LoginIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=4096)
