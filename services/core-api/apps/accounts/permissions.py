"""
RBAC building blocks used by every router. Kept intentionally small: this
is a role gate, not a general permission framework, matching spec §15 Q3
("who may flip auto_reply_allowed") and the four roles in §1.
"""

from collections.abc import Callable, Iterable
from functools import wraps
from typing import Concatenate

from typing import Any, cast

from django.http import HttpRequest
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed
from ninja_jwt.tokens import Token

from apps.accounts.models import RefreshSession, User, UserRole


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


def require_role(*roles: UserRole):
    """Decorator for Django Ninja handlers: `request` must be the first arg
    (Ninja convention) and `request.auth` must be an authenticated User."""

    allowed = {r.value for r in roles}

    def decorator[**P, R](
        fn: Callable[Concatenate[AuthedRequest, P], R],
    ) -> Callable[Concatenate[AuthedRequest, P], R]:
        @wraps(fn)
        def wrapper(request: AuthedRequest, *args: P.args, **kwargs: P.kwargs) -> R:
            user = getattr(request, "auth", None) or getattr(request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                raise HttpError(401, "authentication required")
            if user.role not in allowed:
                raise HttpError(403, f"requires role in {sorted(allowed)}, got {user.role!r}")
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator


def has_any_role(user: object, roles: Iterable[UserRole]) -> bool:
    return getattr(user, "role", None) in {r.value for r in roles}
