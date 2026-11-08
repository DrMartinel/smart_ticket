"""
What a tool result may show the model (BR-F15-09, BR-F15-10): people as
`you` / `someone else` / `none`, text others wrote wrapped as untrusted, and
`[withheld]` for text whose masking failed or that a reviewer holds back.
"""

from __future__ import annotations

from typing import Any

from ai_engine.graph.nodes.injection_patterns import matches

WITHHELD = "[withheld]"
UNTRUSTED = "untrusted_text"
MASKED_LEVELS = frozenset({"routine", "sensitive", "critical"})


def untrusted(text: str | None) -> dict[str, str] | None:
    """Wraps text someone other than the user wrote."""
    return None if text is None else {UNTRUSTED: text}


def person(who: object | None, me: object | None) -> str:
    """A person as the model sees them."""
    if who is None:
        return "none"
    return "you" if me is not None and str(who) == str(me) else "someone else"


def flagged(result: Any) -> bool:
    """Whether any untrusted text in `result` trips the injection screen."""
    if isinstance(result, dict):
        if isinstance(text := result.get(UNTRUSTED), str) and matches(text):
            return True
        return any(flagged(value) for value in result.values())
    if isinstance(result, list):
        return any(flagged(value) for value in result)
    return False


def refusal(body: Any) -> dict[str, Any]:
    """A coded error body (BR-X-08) as the model sees it."""
    if isinstance(body, dict) and "code" in body:
        return {"code": body["code"], "message": body.get("message", "")}
    return {"code": "refused", "message": ""}
