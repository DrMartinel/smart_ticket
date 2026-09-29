from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.accounts.models import User
from apps.accounts.response_schema import UserOut
from apps.accounts.permissions import AuthedRequest

router = Router(tags=["accounts"])


@router.get("/me", auth=JWTAuth(), response=UserOut)
def me(request: AuthedRequest) -> User:
    return request.auth
