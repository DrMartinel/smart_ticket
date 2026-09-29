import pytest

from apps.core.testing import api_client_for


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
    """`api_as(user)` is a test client that sends a real JWT for `user`
    (`apps.core.testing.api_client_for`)."""

    return api_client_for
