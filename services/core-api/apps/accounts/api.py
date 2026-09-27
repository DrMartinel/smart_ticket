from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.accounts.rbac import AuthedRequest

router = Router(tags=["accounts"])


@router.get("/me", auth=JWTAuth())
def me(request: AuthedRequest) -> dict[str, int | str]:
    u = request.auth
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
    }
