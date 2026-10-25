"""
RBAC building blocks used by every router: `SessionAuth` and the role gate
`require_role`, which every route but sign-in, refresh, sign-out and the
lifecycle callback carries (PRE-1).
"""

from collections.abc import Callable, Iterable
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

from apps.accounts.models import RefreshSession, User, UserRole
from apps.audit.models import AuditLog


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


ALL_ROLES = tuple(UserRole)
STAFF = (UserRole.TECHNICIAN, UserRole.MANAGER, UserRole.SECURITY)
TECHNICIAN_OR_MANAGER = (UserRole.TECHNICIAN, UserRole.MANAGER)


class AccessRefusal(StrEnum):
    ROLE_NOT_ALLOWED = "role_not_allowed"


class AccessError(Exception):
    """A refusal in the shared error shape (BR-X-08), answered by `config/urls.py`."""

    status = 403

    def __init__(self, code: AccessRefusal, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


_GATES: WeakKeyDictionary[Callable[..., Any], frozenset[str]] = WeakKeyDictionary()


def allowed_roles(handler: Callable[..., Any]) -> frozenset[str] | None:
    """The roles a handler's `require_role` lets in, or None for an ungated handler."""
    while handler not in _GATES:
        inner = getattr(handler, "__wrapped__", None)
        if inner is None:
            return None
        handler = inner
    return _GATES[handler]


def refuse_unless(request: HttpRequest, user: User, roles: Iterable[UserRole]) -> None:
    """Refuses `user` unless their role is one of `roles`, auditing the refusal."""
    allowed = sorted(r.value for r in roles)
    if user.role not in allowed:
        _refuse(request, user, allowed)


def _refuse(request: HttpRequest, user: User, allowed: list[str]) -> NoReturn:
    match = getattr(request, "resolver_match", None)
    route = match.route if match is not None else request.path
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
            payload={"route": route, "method": request.method, "role": user.role},
            trace_id=getattr(request, "trace_id", None),
        )
    raise AccessError(
        AccessRefusal.ROLE_NOT_ALLOWED,
        f"requires role in [{', '.join(allowed)}]",
        {"role": user.role},
    )


def require_role(*roles: UserRole):
    """Decorator for Django Ninja handlers: `request` must be the first arg
    (Ninja convention) and `request.auth` must be an authenticated User."""

    allowed = frozenset(r.value for r in roles)

    def decorator[**P, R](
        fn: Callable[Concatenate[AuthedRequest, P], R],
    ) -> Callable[Concatenate[AuthedRequest, P], R]:
        @wraps(fn)
        def wrapper(request: AuthedRequest, *args: P.args, **kwargs: P.kwargs) -> R:
            user = getattr(request, "auth", None) or getattr(request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                raise HttpError(401, "authentication required")
            refuse_unless(request, user, roles)
            return fn(request, *args, **kwargs)

        # The handler's signature, its annotations evaluated.
        setattr(wrapper, "__signature__", inspect.signature(fn, eval_str=True))
        _GATES[wrapper] = allowed
        return wrapper

    return decorator


class GatedAuth:
    """A route's auth callback followed by its role check, so a refused caller is refused
    before Ninja reads the request."""

    def __init__(self, auth: Callable[[HttpRequest], Any], roles: frozenset[str]) -> None:
        self.auth = auth
        self.roles = roles

    def __call__(self, request: HttpRequest) -> Any:
        user = self.auth(request)
        if user and getattr(user, "role", None) not in self.roles:
            _refuse(request, user, sorted(self.roles))
        return user


def gate_authentication(routers: Iterable[tuple[str, Any]]) -> None:
    """Moves each gated route's role check into its authentication."""
    for _prefix, router in routers:
        for path_view in router.path_operations.values():
            for operation in path_view.operations:
                roles = allowed_roles(operation.view_func)
                if roles is not None:
                    operation.auth_callbacks = [
                        GatedAuth(callback, roles) for callback in operation.auth_callbacks
                    ]


def has_any_role(user: object, roles: Iterable[UserRole]) -> bool:
    return getattr(user, "role", None) in {r.value for r in roles}
