"""
Generic test helpers. Nothing here knows about a domain app: role-specific
users, sign-in sessions and ai-engine fakes stay in `conftest.py` and the
apps' own testing modules.
"""

from django.test import Client


def api_client_with(token: str) -> Client:
    """A test client that sends `token` as its bearer token, so a request goes
    through URL routing, auth and the response schema exactly as it does in
    production. Calling a handler function directly skips the schema, which
    is where the response shape is decided."""
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")
