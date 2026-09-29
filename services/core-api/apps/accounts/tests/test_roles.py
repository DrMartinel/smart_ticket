"""
Roles — spec §1. Governance checks key off `User.role` (`is_manager` gates
auto-reply authority, ADR-0002), so an account created without a role must
get the least-privileged one. A privileged default would hand that authority
to every new account without any visible change.
"""

import pytest

from apps.accounts.models import User, UserRole


@pytest.mark.django_db
def test_a_new_user_defaults_to_employee(django_user_model):
    user = django_user_model.objects.create_user(username="new", password="x")

    assert user.role == UserRole.EMPLOYEE.value
    assert not user.is_manager


@pytest.mark.parametrize("role", list(UserRole))
def test_only_the_manager_role_is_a_manager(role):
    assert User(username="u", role=role.value).is_manager is (role is UserRole.MANAGER)
