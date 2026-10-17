"""The identity management commands (F13)."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_break_glass_is_refused_past_the_limit(django_user_model, settings):
    """BR-F13-06: at most `identity.max_break_glass_accounts` flagged accounts."""
    limit = settings.THRESHOLDS.identity.max_break_glass_accounts
    for i in range(limit + 1):
        django_user_model.objects.create_user(username=f"m{i}", password="x", role="manager")
    for i in range(limit):
        call_command("set_break_glass", f"m{i}", stdout=StringIO())

    with pytest.raises(CommandError, match="limit"):
        call_command("set_break_glass", f"m{limit}", stdout=StringIO())
    assert User.objects.filter(is_break_glass=True).count() == limit


def test_break_glass_is_refused_for_a_non_manager(technician_user):
    with pytest.raises(CommandError, match="only a manager"):
        call_command("set_break_glass", "tech", stdout=StringIO())


def test_the_link_report_lists_unlinked_local_users(technician_user, django_user_model):
    django_user_model.objects.create_user(username="linked", external_id="sub-1")
    out = StringIO()

    call_command("identity_link_report", stdout=out)

    assert "tech" in out.getvalue()
    assert "linked" not in out.getvalue().replace("unlinked", "")
    assert "1 local user(s)" in out.getvalue()
