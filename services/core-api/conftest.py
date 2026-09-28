import pytest


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
