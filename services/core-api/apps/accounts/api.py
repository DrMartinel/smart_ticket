from ninja import Router
from ninja_jwt.authentication import JWTAuth

router = Router(tags=["accounts"])


@router.get("/me", auth=JWTAuth())
def me(request):
    u = request.auth
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
    }
