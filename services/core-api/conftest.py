# pyright: standard
import pytest
from django.test import Client


@pytest.fixture
def manager_user(django_user_model):
    u = django_user_model.objects.create_user(username="mgr", password="x", role="manager")
    return u


@pytest.fixture
def employee_user(django_user_model):
    u = django_user_model.objects.create_user(username="emp", password="x", role="employee")
    return u


@pytest.fixture
def technician_user(django_user_model):
    u = django_user_model.objects.create_user(username="tech", password="x", role="technician")
    return u


@pytest.fixture
def api_as():
    """`api_as(user)` is a test client that sends a real JWT for `user`, so a
    request goes through URL routing, auth and the response schema exactly
    as it does in production. Calling a handler function directly skips the
    schema, which is where the response shape is decided."""

    # Imported here, not at module top: ninja_jwt reads Django settings on
    # import, and a whole-workspace run loads this conftest before
    # evals/suites/conftest.py has configured Django.
    from ninja_jwt.tokens import AccessToken

    def client_for(user) -> Client:
        # for_user is a classmethod on ninja_jwt's untyped Token base.
        token = AccessToken.for_user(user)  # pyright: ignore[reportAttributeAccessIssue]
        return Client(HTTP_AUTHORIZATION=f"Bearer {token}")

    return client_for
