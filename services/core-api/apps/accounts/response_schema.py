"""
Response shapes for the account endpoints.
"""

from __future__ import annotations

from ninja import Schema


class UserOut(Schema):
    id: int
    username: str
    email: str
    role: str
