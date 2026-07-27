"""
RBAC building blocks used by every router. Kept intentionally small: this
is a role gate, not a general permission framework, matching spec §15 Q3
("who may flip auto_reply_allowed") and the four roles in §1.
"""

from functools import wraps
from typing import Iterable

from ninja.errors import HttpError

from contracts.enums import UserRole


def require_role(*roles: UserRole):
    """Decorator for Django Ninja handlers: `request` must be the first arg
    (Ninja convention) and `request.auth` must be an authenticated User."""

    allowed = {r.value for r in roles}

    def decorator(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            user = getattr(request, "auth", None) or getattr(request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                raise HttpError(401, "authentication required")
            if user.role not in allowed:
                raise HttpError(403, f"requires role in {sorted(allowed)}, got {user.role!r}")
            return fn(request, *args, **kwargs)

        return wrapper

    return decorator


def has_any_role(user, roles: Iterable[UserRole]) -> bool:
    return getattr(user, "role", None) in {r.value for r in roles}
