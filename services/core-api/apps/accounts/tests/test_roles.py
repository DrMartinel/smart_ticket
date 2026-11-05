"""A new account's base role, and which base role holds page authority."""

import pytest

from apps.accounts.models import User, UserRole
from apps.accounts.utils.access import Access
from apps.accounts.utils.catalog import Permission


@pytest.mark.django_db
def test_a_new_user_defaults_to_employee(django_user_model):
    user = django_user_model.objects.create_user(username="new", password="x")

    assert user.role == UserRole.EMPLOYEE.value
    assert not Access.of(user).holds(Permission.KB_AUTHORITY_GRANT)


@pytest.mark.django_db
@pytest.mark.parametrize("role", list(UserRole))
def test_only_the_manager_base_role_grants_page_authority(role):
    user = User.objects.create_user(username="u", password="x", role=role.value)

    assert Access.of(user).holds(Permission.KB_AUTHORITY_GRANT) is (role is UserRole.MANAGER)
