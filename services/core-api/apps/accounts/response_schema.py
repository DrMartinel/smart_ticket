"""
Response shapes for the account endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema


class UserOut(Schema):
    id: uuid.UUID
    username: str
    email: str
    role: str


class SessionOut(Schema):
    access: str
    access_expires_at: datetime
    user: UserOut


class SignInOut(Schema):
    id: uuid.UUID
    family: uuid.UUID
    client: str
    user_agent: str
    ip_address: str | None
    created_at: datetime
    expires_at: datetime
    family_expires_at: datetime


class RefusedOut(Schema):
    detail: str
