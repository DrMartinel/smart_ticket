"""Request shapes for the account endpoints."""

from __future__ import annotations

from ninja import Field, Schema


class LoginIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=4096)
