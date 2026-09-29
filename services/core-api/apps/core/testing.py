"""
Generic test helpers. Nothing here knows about a domain app: role-specific
users and ai-engine fakes stay in `conftest.py`.
"""

from typing import Any

from django.test import Client


def api_client_for(user: Any) -> Client:
    """A test client that sends a real JWT for `user`, so a request goes
    through URL routing, auth and the response schema exactly as it does in
    production. Calling a handler function directly skips the schema, which
    is where the response shape is decided."""

    # Imported here, not at module top: ninja_jwt reads Django settings on
    # import, and a whole-workspace run loads conftest before
    # evals/suites/conftest.py has configured Django.
    from ninja_jwt.tokens import AccessToken

    # for_user is a classmethod on ninja_jwt's untyped Token base, which mypy
    # misreads as an instance method.
    token = AccessToken.for_user(user)  # type: ignore[misc]
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")
