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


def agent_token_for(
    user: User,
    *,
    conversation: uuid.UUID | None = None,
    turn: uuid.UUID | None = None,
    family_hours: float = 1,
) -> str:
    """An agent turn's token for `user`, minted from a real chat sign-in (ADR-0046), for a running
    turn: the one named if it exists, else a new one with the ids given."""
    from apps.agent.models import AgentConversation, AgentTurn, AgentTurnState

    now = timezone.now()
    family = uuid.uuid4()
    sessions.new_token(
        user,
        AuthClient.CHAT,
        family,
        now=now,
        family_ends=now + timedelta(hours=family_hours),
        requester=Requester(user_agent="tests", ip_address=None),
    )
    existing = AgentTurn.objects.filter(id=turn).first() if turn is not None else None
    if existing is None:
        chat = AgentConversation.objects.create(
            id=conversation or uuid.uuid4(), user=user, surface="chat"
        )
        existing = AgentTurn.objects.create(
            id=turn or uuid.uuid4(),
            conversation=chat,
            seq=1,
            message_masked="Help me with my ticket.",
            pii_level="routine",
            session_family=family,
            state=AgentTurnState.RUNNING.value,
        )
    return sessions.issue_for_agent(
        user, family, conversation=existing.conversation_id, turn=existing.id
    )


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
