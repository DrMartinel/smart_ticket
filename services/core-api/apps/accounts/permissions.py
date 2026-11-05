"""
RBAC building blocks used by every router: `SessionAuth` and the permission gate
`require`, which every route but sign-in, refresh, sign-out and the callbacks
carries (PRE-1, ADR-0045).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from functools import wraps
import inspect
from typing import Any, Concatenate, NoReturn, cast
from weakref import WeakKeyDictionary

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed
from ninja_jwt.tokens import Token

from apps.accounts.models import RefreshSession, RefusedCall, User
from apps.accounts.utils.access import Access
from apps.accounts.utils.catalog import Permission
from apps.audit.models import AuditLog
from apps.core.errors import CodedError


class AuthedRequest(HttpRequest):
    """A request that passed Ninja's auth: `request.auth` is the user."""

    auth: User


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
        return user


class AccessRefusal(StrEnum):
    PERMISSION_MISSING = "permission_missing"


class AccessError(CodedError):
    """A caller outside a route's roles and capabilities."""

    code: AccessRefusal

    def __init__(self, code: AccessRefusal, message: str, details: dict[str, Any]) -> None:
        super().__init__(403, code, message, details)


@dataclass(frozen=True)
class Gate:
    """The permission a route needs, held at any scope (ADR-0045)."""

    permission: Permission

    def admits(self, user: User) -> bool:
        return Access.of(user).holds(self.permission)

    def describe(self) -> str:
        return f"requires permission {self.permission.value}"


_GATES: WeakKeyDictionary[Callable[..., Any], Gate] = WeakKeyDictionary()


def gate_of(handler: Callable[..., Any]) -> Gate | None:
    """The gate on a handler, or None for an ungated handler."""
    while handler not in _GATES:
        inner = getattr(handler, "__wrapped__", None)
        if inner is None:
            return None
        handler = inner
    return _GATES[handler]


def refuse_without(request: HttpRequest, user: User, permission: Permission) -> None:
    """Refuses `user` unless they hold `permission`, auditing the refusal."""
    gate = Gate(permission)
    if not gate.admits(user):
        _refuse(request, user, gate)


def refuse_unless_covers(
    request: HttpRequest, user: User, permission: Permission, ticket: Any
) -> None:
    """Refuses `user` unless `permission` reaches `ticket` by team or department."""
    if not Access.of(user).covers_ticket(permission, ticket):
        _refuse(request, user, Gate(permission))


def _refuse(request: HttpRequest, user: User, gate: Gate) -> NoReturn:
    match = getattr(request, "resolver_match", None)
    route = match.route if match is not None else request.path
    RefusedCall.objects.create(user=user, route=route[:200])
    window = timedelta(seconds=settings.THRESHOLDS.access_denied.audit_window_seconds)
    recently_audited = AuditLog.objects.filter(
        event="access_denied",
        actor_id=user.id,
        payload__route=route,
        payload__method=request.method,
        occurred_at__gte=timezone.now() - window,
    ).exists()
    if not recently_audited:
        AuditLog.objects.record(
            "access_denied",
            actor_type="human",
            actor_id=user.id,
            payload={
                "route": route,
                "method": request.method,
                "role": user.role,
                "permission": gate.permission.value,
            },
            trace_id=getattr(request, "trace_id", None),
        )
    raise AccessError(
        AccessRefusal.PERMISSION_MISSING,
        gate.describe(),
        {"role": user.role, "permission": gate.permission.value},
    )


def require(permission: Permission):
    """Decorator for Django Ninja handlers: lets in a user who holds `permission`.
    `request` must be the first arg and `request.auth` an authenticated User."""

    gate = Gate(permission)

    def decorator[**P, R](
        fn: Callable[Concatenate[AuthedRequest, P], R],
    ) -> Callable[Concatenate[AuthedRequest, P], R]:
        @wraps(fn)
        def wrapper(request: AuthedRequest, *args: P.args, **kwargs: P.kwargs) -> R:
            user = getattr(request, "auth", None) or getattr(request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                raise HttpError(401, "authentication required")
            if not gate.admits(user):
                _refuse(request, user, gate)
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
        user = self.auth(request)
        if user and not self.gate.admits(user):
            _refuse(request, user, self.gate)
        return user

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


def holds(user: User, permission: Permission) -> bool:
    """Whether `user` holds `permission` anywhere."""
    return Access.of(user).holds(permission)
