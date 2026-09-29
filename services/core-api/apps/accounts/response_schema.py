"""
Response shapes for the account endpoints.
"""

from __future__ import annotations

import uuid

from ninja import Schema


class UserOut(Schema):
    id: uuid.UUID
    username: str
    email: str
    role: str
