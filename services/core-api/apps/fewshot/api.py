from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.fewshot.services import active_examples_for_category

router = Router(tags=["fewshot"])


@router.get("/category/{category}", auth=JWTAuth())
def list_active(request, category: str):
    examples = active_examples_for_category(category)
    return [
        {
            "id": e.id,
            "category": e.category,
            "input_text": e.input_text,
            "output_json": e.output_json,
            "expires_at": e.expires_at.isoformat(),
        }
        for e in examples
    ]
