"""Test helpers for signed-in requests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from django.test import Client
from django.utils import timezone

from apps.accounts.models import AuthClient, User
from apps.accounts.utils import Requester, sessions
from apps.core.testing import api_client_with


def api_client_for(user: User, client: AuthClient = AuthClient.ADMIN) -> Client:
    """A test client signed in as `user` through a real session, as the frontends are."""
    now = timezone.now()
    raw, session = sessions.new_token(
        user,
        client,
        uuid.uuid4(),
        now=now,
        family_ends=now + timedelta(hours=1),
        requester=Requester(user_agent="tests", ip_address=None),
    )
    return api_client_with(sessions.issue(session, raw).access)


def grant_capability(user: User, capability: str) -> None:
    """Grants `user` the add-on role for `capability` everywhere, as the console would."""
    from apps.accounts.models import Assignment, Capability, Role
    from apps.accounts.utils.access import Access
    from apps.accounts.utils.catalog import ADD_ON_ROLES

    role = Role.objects.get(urn=ADD_ON_ROLES[Capability(capability)].value)
    Assignment.objects.get_or_create(
        user=user,
        role=role,
        scope_kind="global",
        ended_at=None,
        defaults={"starts_at": datetime(2000, 1, 1, tzinfo=UTC)},
    )
    Access.forget(user)
