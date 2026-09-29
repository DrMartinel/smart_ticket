"""
The role gate for Ninja handlers, `require_role`. It must refuse a request
with no authenticated user (401) and a user outside the allowed roles (403)
before the handler runs. A gate that lets a call through on a missing or
unexpected user is worse than none, because the endpoint looks protected.
"""

from typing import cast

import pytest
from django.test import RequestFactory
from ninja.errors import HttpError

from apps.accounts.models import User, UserRole

from common.permissions import AuthedRequest, has_any_role, require_role


class Handler:
    """A decorated handler that records whether it ran."""

    def __init__(self) -> None:
        self.calls = 0

        @require_role(UserRole.MANAGER, UserRole.SECURITY)
        def handle(request: AuthedRequest) -> str:
            self.calls += 1
            return "ran"

        self.handle = handle


def request_as(user: User | None) -> AuthedRequest:
    request = cast(AuthedRequest, RequestFactory().get("/"))
    if user is not None:
        request.auth = user
    return request


def test_no_authenticated_user_is_refused_with_401():
    handler = Handler()

    with pytest.raises(HttpError) as refused:
        handler.handle(request_as(None))

    assert refused.value.status_code == 401
    assert handler.calls == 0


def test_a_role_outside_the_allowed_set_is_refused_with_403():
    handler = Handler()

    with pytest.raises(HttpError) as refused:
        handler.handle(request_as(User(username="t", role=UserRole.TECHNICIAN.value)))

    assert refused.value.status_code == 403
    assert handler.calls == 0


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.SECURITY])
def test_an_allowed_role_reaches_the_handler(role):
    handler = Handler()

    assert handler.handle(request_as(User(username="m", role=role.value))) == "ran"
    assert handler.calls == 1


def test_has_any_role():
    manager = User(username="m", role=UserRole.MANAGER.value)

    assert has_any_role(manager, [UserRole.MANAGER])
    assert not has_any_role(manager, [UserRole.EMPLOYEE, UserRole.TECHNICIAN])
    assert not has_any_role(object(), [UserRole.MANAGER])
