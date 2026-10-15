"""Test helpers for signed-in requests."""

from __future__ import annotations

import uuid
from datetime import timedelta

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
