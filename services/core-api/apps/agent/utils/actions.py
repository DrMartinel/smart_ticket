"""Calls an agent made on `confirm` and `human_only` routes: storing them, and applying one when a
person sends it with their own session (F15, ADR-0046 §7–8)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from pydantic_core import to_jsonable_python

from apps.accounts.models import User
from apps.agent.models import AgentAction, AgentActionKind, AgentActionState
from apps.audit.context import audit_context
from apps.audit.models import AuditLog
from apps.core.errors import CodedError

# The header a client sends with a call to apply the agent action it names.
AGENT_ACTION_HEADER = "X-Agent-Action"
# Path parameters that name what an action is about, and the kind of thing each names.
_TARGETS = {"item_id": "review_item", "public_id": "ticket", "execution_id": "runbook_execution"}


class AgentActionRefusal(StrEnum):
    MISMATCH = "agent_action_mismatch"
    NOT_PENDING = "agent_action_not_pending"
    EXPIRED = "agent_action_expired"


class AgentActionError(CodedError):
    """An apply core-api refuses."""

    code: AgentActionRefusal


class AgentActionPending(Exception):
    """An agent's call on a `confirm` route, stored and waiting for the user; answered 202."""

    def __init__(self, action: AgentAction) -> None:
        super().__init__(str(action.id))
        self.action = action


@dataclass(frozen=True)
class AgentCall:
    """One call to a route: its method, route pattern, concrete path and validated arguments."""

    method: str
    route: str
    path: str
    arguments: dict[str, Any]

    @classmethod
    def of(cls, request: HttpRequest, kwargs: dict[str, Any]) -> AgentCall:
        match = getattr(request, "resolver_match", None)
        return cls(
            method=request.method or "",
            route=match.route if match is not None else request.path,
            path=request.path,
            arguments={
                name: to_jsonable_python(value)
                for name, value in kwargs.items()
                if not isinstance(value, HttpResponse)
            },
        )

    def sha256(self) -> str:
        canonical = json.dumps(
            {
                "method": self.method,
                "route": self.route,
                "path": self.path,
                "arguments": self.arguments,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class AgentOrigin:
    """The agent turn a call came from, and the tool that made it."""

    conversation: uuid.UUID
    turn: uuid.UUID
    tool: str

    def audit_fields(self) -> dict[str, str]:
        return {
            "via": "agent",
            "agent_conversation_id": str(self.conversation),
            "agent_turn_id": str(self.turn),
            "agent_tool": self.tool,
        }


_applying: ContextVar[AgentAction | None] = ContextVar("agent_action_applying", default=None)


class AgentActions:
    """Stores the calls an agent may not make itself and applies them for a person."""

    def propose(
        self, kind: AgentActionKind, user: User, call: AgentCall, origin: AgentOrigin
    ) -> AgentAction:
        """Stores `call` as a pending confirm or draft and audits it."""
        th = settings.THRESHOLDS.agent
        lifetime = (
            timedelta(minutes=th.confirm_ttl_minutes)
            if kind is AgentActionKind.CONFIRM
            else timedelta(hours=th.draft_ttl_hours)
        )
        target_kind, target_ref = next(
            (
                (kind, str(call.arguments[name]))
                for name, kind in _TARGETS.items()
                if name in call.arguments
            ),
            ("", ""),
        )
        with transaction.atomic():
            action = AgentAction.objects.create(
                kind=kind.value,
                user=user,
                conversation_id=origin.conversation,
                turn_id=origin.turn,
                tool=origin.tool,
                method=call.method,
                route=call.route,
                path=call.path,
                arguments=call.arguments,
                arguments_sha256=call.sha256(),
                target_kind=target_kind,
                target_ref=target_ref[:64],
                expires_at=timezone.now() + lifetime,
            )
            AuditLog.objects.record(
                "agent_action_proposed"
                if kind is AgentActionKind.CONFIRM
                else "agent_draft_created",
                actor_type="human",
                actor_id=user.id,
                payload={
                    "route": call.route,
                    "method": call.method,
                    "agent_action_id": str(action.id),
                    **origin.audit_fields(),
                },
            )
        return action

    @contextmanager
    def applying(self, action_id: str, user: User, call: AgentCall) -> Iterator[AgentAction]:
        """Runs the block as `user` applying their pending action `action_id`, in one
        transaction; the action is applied only if the block succeeds."""
        try:
            key = uuid.UUID(action_id)
        except ValueError as e:
            raise self._not_pending() from e
        now = timezone.now()
        if AgentAction.objects.filter(
            id=key, user=user, state=AgentActionState.PENDING.value, expires_at__lte=now
        ).update(state=AgentActionState.EXPIRED.value, resolved_at=now):
            raise AgentActionError(410, AgentActionRefusal.EXPIRED, "this action has expired")
        with transaction.atomic():
            action = (
                AgentAction.objects.select_for_update()
                .filter(id=key, user=user, state=AgentActionState.PENDING.value)
                .first()
            )
            if action is None:
                raise self._not_pending()
            confirm = action.kind == AgentActionKind.CONFIRM.value
            same_call = (
                action.arguments_sha256 == call.sha256() if confirm else action.path == call.path
            )
            if (action.method, action.route) != (call.method, call.route) or not same_call:
                raise AgentActionError(
                    409,
                    AgentActionRefusal.MISMATCH,
                    "this call is not the one the assistant proposed",
                )
            origin = AgentOrigin(action.conversation_id, action.turn_id, action.tool)
            fields = (
                {
                    **origin.audit_fields(),
                    "agent_action_id": str(action.id),
                    "confirmed_by": str(user.id),
                }
                if confirm
                else {"agent_draft_id": str(action.id)}
            )
            token = _applying.set(action)
            try:
                with audit_context(fields):
                    yield action
                    AuditLog.objects.record(
                        "agent_action_applied",
                        actor_type="human",
                        actor_id=user.id,
                        payload={
                            "route": action.route,
                            "method": action.method,
                            "kind": action.kind,
                        },
                    )
            finally:
                _applying.reset(token)
            action.state = AgentActionState.APPLIED.value
            action.resolved_at = timezone.now()
            action.resolved_by = user
            action.save(update_fields=["state", "resolved_at", "resolved_by"])

    def draft_being_applied(self) -> uuid.UUID | None:
        """The agent draft the current request is applying, if any."""
        action = _applying.get()
        if action is None or action.kind != AgentActionKind.DRAFT.value:
            return None
        return action.id

    @staticmethod
    def _not_pending() -> AgentActionError:
        return AgentActionError(
            409, AgentActionRefusal.NOT_PENDING, "no pending action of yours has this id"
        )


agent_actions = AgentActions()
