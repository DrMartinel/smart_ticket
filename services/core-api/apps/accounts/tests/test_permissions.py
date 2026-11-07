"""
The permission gate for Ninja handlers, `require`. It must refuse a request
with no authenticated user (401) and a user without the permission (403)
before the handler runs.
"""

from typing import cast

import pytest
from django.test import RequestFactory
from ninja.errors import HttpError

from apps.accounts.models import User, UserRole
from apps.accounts.permissions import (
    AccessError,
    AccessRefusal,
    AuthedRequest,
    Caller,
    require,
)
from apps.accounts.utils.catalog import Permission


class Handler:
    """A decorated handler that records whether it ran."""

    def __init__(self) -> None:
        self.calls = 0

        @require(Permission.SECURITY_SUMMARY_READ)
        def handle(request: AuthedRequest) -> str:
            self.calls += 1
            return "ran"

        self.handle = handle


def request_as(user: User | None) -> AuthedRequest:
    request = cast(AuthedRequest, RequestFactory().get("/"))
    if user is not None:
        request.auth = Caller(user, route="/", method="GET")
    return request


def test_no_authenticated_user_is_refused_with_401():
    handler = Handler()

    with pytest.raises(HttpError) as refused:
        handler.handle(request_as(None))

    assert refused.value.status_code == 401
    assert handler.calls == 0


@pytest.mark.django_db
def test_a_person_without_the_permission_is_refused_with_403():
    handler = Handler()
    technician = User.objects.create_user(username="t", password="x", role="technician")

    with pytest.raises(AccessError) as refused:
        handler.handle(request_as(technician))

    assert refused.value.status == 403
    assert refused.value.code is AccessRefusal.PERMISSION_MISSING
    assert handler.calls == 0


@pytest.mark.django_db
@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.SECURITY])
def test_a_role_holding_the_permission_reaches_the_handler(role):
    handler = Handler()

    assert handler.handle(request_as(User(username="m", role=role.value))) == "ran"
    assert handler.calls == 1


@pytest.mark.django_db
def test_holds_reads_the_base_role():
    manager = User(username="m", role=UserRole.MANAGER.value)

    caller = Caller(manager, route="/", method="GET")

    assert caller.holds(Permission.ROLLOUT_FLAG_ON)
    assert not caller.holds(Permission.SECURITY_QUEUE_WORK)
