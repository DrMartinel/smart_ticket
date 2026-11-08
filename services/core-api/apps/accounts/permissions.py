"""
RBAC building blocks used by every router: `SessionAuth` and the permission gate
`require`, which every route but sign-in, refresh, sign-out and the callbacks
carries (PRE-1, ADR-0045). The gate also holds each route's agent tier, which
decides what a token an agent turn uses may do there (ADR-0046).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from functools import wraps
import inspect
import re
import uuid
from typing import Any, Concatenate, NoReturn, assert_never, cast
from weakref import WeakKeyDictionary

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed
from ninja_jwt.tokens import Token

from apps.accounts.models import RefreshSession, RefusedCall, User
from apps.accounts.utils import AGENT_ACT
from apps.accounts.utils.access import Access
from apps.accounts.utils.catalog import Permission
from apps.agent.models import (
    AgentActionKind,
    AgentConversationState,
    AgentTurn,
    AgentTurnState,
)
from apps.agent.utils.actions import (
    AGENT_ACTION_HEADER,
    AgentActionPending,
    AgentCall,
    AgentOrigin,
    agent_actions,
)
from apps.agent.utils.vocabulary import AgentError, AgentRefusal
from apps.audit.context import audit_context
from apps.audit.models import AuditLog
from apps.core.errors import CodedError


# The header an agent's call names its tool in, and the shape of a tool's name.
AGENT_TOOL_HEADER = "X-Agent-Tool"
TOOL_NAME = re.compile(r"^[a-z][a-z_]{0,39}$")


class AgentTier(StrEnum):
    """What a token an agent turn uses may do on a route (ADR-0046 §5)."""

    READ = "read"
    SELF = "self"
    CONFIRM = "confirm"
    HUMAN_ONLY = "human_only"
    NONE = "none"


class SessionAuth(JWTAuth):
    """Accepts an access token only while the sign-in it was issued to is live (ADR-0029)."""

    def jwt_authenticate(self, request: HttpRequest, token: str) -> Any:
        # ninja_jwt annotates both as returning classes; they return a token and a user.
        validated = cast(Token, self.get_validated_token(token))
        user = cast(User, self.get_user(validated))
        family = validated.get("sid")
        if not family or not RefreshSession.objects.live_family(family).filter(user=user).exists():
            raise AuthenticationFailed("the sign-in this token belongs to has ended")
        request.user = user
        act = validated.get("act")
        agent = None
        if act is not None:
            try:
                if act != AGENT_ACT:
                    raise ValueError(act)
                conversation, turn = uuid.UUID(validated["agc"]), uuid.UUID(validated["agt"])
            except (KeyError, TypeError, ValueError) as e:
                raise AuthenticationFailed("this token's actor is not one core-api issues") from e
            if not AgentTurn.objects.filter(
                id=turn,
                conversation_id=conversation,
                state=AgentTurnState.RUNNING.value,
                conversation__user=user,
                conversation__state=AgentConversationState.ACTIVE.value,
            ).exists():
                raise AuthenticationFailed("the agent turn this token belongs to is not running")
            tool = request.headers.get(AGENT_TOOL_HEADER, "")
            agent = AgentOrigin(conversation, turn, tool if TOOL_NAME.match(tool) else "")
        match = getattr(request, "resolver_match", None)
        return Caller(
            user=user,
            route=match.route if match is not None else request.path,
            method=request.method or "",
            trace_id=getattr(request, "trace_id", None),
            agent=agent,
            session_family=uuid.UUID(family),
        )


class AccessRefusal(StrEnum):
    PERMISSION_MISSING = "permission_missing"
    AGENT_NOT_ALLOWED = "agent_not_allowed"
    HUMAN_ONLY_ACTION = "human_only_action"


class AccessError(CodedError):
    """A caller without a route's permission."""

    code: AccessRefusal

    def __init__(self, code: AccessRefusal, message: str, details: dict[str, Any]) -> None:
        super().__init__(403, code, message, details)


@dataclass(frozen=True)
class Gate:
    """The permission a route needs, held at any scope (ADR-0045), and its agent tier
    (ADR-0046); a route with no tier refuses agents."""

    permission: Permission
    agent_tier: AgentTier | None = None


@dataclass(frozen=True)
class Caller:
    """Who an authenticated request comes from and the route it calls: the user, and the
    agent turn and tool acting for them, None when the user sent it. Admits or refuses
    itself."""

    user: User
    route: str
    method: str
    trace_id: str | None = None
    agent: AgentOrigin | None = None
    session_family: uuid.UUID | None = None

    def holds(self, permission: Permission) -> bool:
        return Access.of(self.user).holds(permission)

    def require(self, permission: Permission) -> None:
        """Refuses this caller unless they hold `permission`."""
        if not self.holds(permission):
            self.refuse(Gate(permission))

    def require_covering(self, permission: Permission, ticket: Any) -> None:
        """Refuses this caller unless `permission` reaches `ticket` by team or department."""
        if not Access.of(self.user).covers_ticket(permission, ticket):
            self.refuse(Gate(permission))

    def admit(self, gate: Gate) -> None:
        """Refuses this caller without the gate's permission, then any agent acting for them
        on a route whose tier refuses agents."""
        self.require(gate.permission)
        if self.agent is not None and gate.agent_tier in (None, AgentTier.NONE):
            AuditLog.objects.record(
                "agent_call_refused",
                actor_type="human",
                actor_id=self.user.id,
                payload={
                    "route": self.route,
                    "method": self.method,
                    "permission": gate.permission.value,
                    **self.agent.audit_fields(),
                },
                trace_id=self.trace_id,
            )
            raise AccessError(
                AccessRefusal.AGENT_NOT_ALLOWED,
                "an agent may not call this route",
                {"permission": gate.permission.value},
            )

    def refuse(self, gate: Gate) -> NoReturn:
        """Refuses this caller for lacking the gate's permission, auditing it once a window."""
        RefusedCall.objects.create(user=self.user, route=self.route[:200])
        window = timedelta(seconds=settings.THRESHOLDS.access_denied.audit_window_seconds)
        recently_audited = AuditLog.objects.filter(
            event="access_denied",
            actor_id=self.user.id,
            payload__route=self.route,
            payload__method=self.method,
            occurred_at__gte=timezone.now() - window,
        ).exists()
        if not recently_audited:
            AuditLog.objects.record(
                "access_denied",
                actor_type="human",
                actor_id=self.user.id,
                payload={
                    "route": self.route,
                    "method": self.method,
                    "role": self.user.role,
                    "permission": gate.permission.value,
                    **(self.agent.audit_fields() if self.agent else {}),
                },
                trace_id=self.trace_id,
            )
        raise AccessError(
            AccessRefusal.PERMISSION_MISSING,
            f"requires permission {gate.permission.value}",
            {"role": self.user.role, "permission": gate.permission.value},
        )


class AuthedRequest(HttpRequest):
    """A request that passed Ninja's auth: `request.auth` is its caller."""

    auth: Caller


_GATES: WeakKeyDictionary[Callable[..., Any], Gate] = WeakKeyDictionary()


def gate_of(handler: Callable[..., Any]) -> Gate | None:
    """The gate on a handler, or None for an ungated handler."""
    while handler not in _GATES:
        inner = getattr(handler, "__wrapped__", None)
        if inner is None:
            return None
        handler = inner
    return _GATES[handler]


def require(permission: Permission, *, agent: AgentTier | None = None):
    """Decorator for Django Ninja handlers: lets in a user who holds `permission`, and an agent
    acting for them as the route's `agent` tier allows. `request` must be the first arg and
    `request.auth` its `Caller`."""

    gate = Gate(permission, agent)

    def decorator[**P, R](
        fn: Callable[Concatenate[AuthedRequest, P], R],
    ) -> Callable[Concatenate[AuthedRequest, P], R]:
        @wraps(fn)
        def wrapper(request: AuthedRequest, *args: P.args, **kwargs: P.kwargs) -> R:
            caller = getattr(request, "auth", None)
            if not isinstance(caller, Caller) or not caller.user.is_authenticated:
                raise HttpError(401, "authentication required")
            caller.admit(gate)
            if caller.agent is not None:
                if gate.agent_tier is not AgentTier.READ and not AgentTurn.objects.count_write(
                    caller.agent.turn, settings.THRESHOLDS.agent.max_tool_calls_per_turn
                ):
                    raise AgentError(
                        429, AgentRefusal.TOOL_LIMIT, "this turn has made all its write calls"
                    )
                match gate.agent_tier:
                    case AgentTier.READ | AgentTier.SELF:
                        with audit_context(caller.agent.audit_fields()):
                            return fn(request, *args, **kwargs)
                    case AgentTier.CONFIRM:
                        raise AgentActionPending(
                            agent_actions.propose(
                                AgentActionKind.CONFIRM,
                                caller.user,
                                AgentCall.of(request, kwargs),
                                caller.agent,
                            )
                        )
                    case AgentTier.HUMAN_ONLY:
                        draft = agent_actions.propose(
                            AgentActionKind.DRAFT,
                            caller.user,
                            AgentCall.of(request, kwargs),
                            caller.agent,
                        )
                        raise AccessError(
                            AccessRefusal.HUMAN_ONLY_ACTION,
                            "human-only action",
                            {"draft_id": str(draft.id)},
                        )
                    case AgentTier.NONE | None:
                        raise AssertionError("Caller.admit refuses an agent on this route")
                    case _:
                        assert_never(gate.agent_tier)
            action_id = request.headers.get(AGENT_ACTION_HEADER)
            if action_id:
                with agent_actions.applying(action_id, caller.user, AgentCall.of(request, kwargs)):
                    return fn(request, *args, **kwargs)
            return fn(request, *args, **kwargs)

        # The handler's signature, its annotations evaluated.
        setattr(wrapper, "__signature__", inspect.signature(fn, eval_str=True))
        _GATES[wrapper] = gate
        return wrapper

    return decorator


class GatedAuth:
    """A route's auth callback followed by its gate, so a refused caller is refused
    before Ninja reads the request."""

    def __init__(self, auth: Callable[[HttpRequest], Any], gate: Gate) -> None:
        self.auth = auth
        self.gate = gate

    def __call__(self, request: HttpRequest) -> Any:
        caller = self.auth(request)
        if caller:
            caller.admit(self.gate)
        return caller

    def __getattr__(self, name: str) -> Any:
        """The wrapped auth's other attributes, e.g. the scheme the API docs show."""
        return getattr(self.auth, name)


def gate_authentication(routers: Iterable[tuple[str, Any]]) -> None:
    """Moves each gated route's role and capability check into its authentication."""
    for _prefix, router in routers:
        for path_view in router.path_operations.values():
            for operation in path_view.operations:
                gate = gate_of(operation.view_func)
                if gate is not None:
                    operation.auth_callbacks = [
                        GatedAuth(callback, gate) for callback in operation.auth_callbacks
                    ]
