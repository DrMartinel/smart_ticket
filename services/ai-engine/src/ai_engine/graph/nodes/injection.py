"""
Injection Detector — spec §6.2 node `detect_inject`, runs FIRST, before
any retrieval or LLM cost is spent. Attachments are treated as fully
untrusted (spec §5.2) — this build doesn't fetch/parse attachment
content at all, which is the simplest way to honor "coi như untrusted
hoàn toàn": nothing from an attachment ever reaches the prompt.
"""

from __future__ import annotations

import re

from ai_engine.graph.state import InjectionVerdict, TriageState

# Compiled once at import, not per instance. Shared read-only by every
# InjectionNode; `re.Pattern` objects are themselves thread-safe.
DEFAULT_PATTERNS: dict[str, re.Pattern] = {
    "ignore_instructions_en": re.compile(
        r"(?i)\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all)\b.{0,30}\b(instructions?|rules?|prompt)\b"
    ),
    "ignore_instructions_vi": re.compile(
        r"(?i)\b(bỏ qua|quên)\b.{0,20}\b(hướng dẫn|chỉ dẫn|quy tắc|lệnh)\b.{0,20}\b(trên|phía trên|trước đó)\b"
    ),
    "role_override_en": re.compile(
        r"(?i)\byou are now\b|\bact as\b|\bnew system prompt\b|\bDAN mode\b"
    ),
    # NOTE: "bạn" is required adjacent to "bây giờ là" in either word
    # order — "bây giờ là" alone is an ordinary Vietnamese phrase for
    # telling the time ("bây giờ là 3 giờ chiều") and would false-positive
    # on ordinary tickets if matched without that anchor.
    "role_override_vi": re.compile(
        r"(?i)\bbạn bây giờ là\b|\bbây giờ bạn là\b|\bhãy đóng vai\b|\bquên vai trò\b"
    ),
    "priority_manipulation": re.compile(
        r"(?i)\b(set|đặt)\b.{0,15}\bpriority\b.{0,10}\b(p0|p1|critical|urgent|khẩn cấp)\b"
    ),
    "system_prompt_probe": re.compile(
        r"(?i)\b(print|show|reveal|repeat)\b.{0,15}\b(system prompt|instructions)\b"
    ),
    "auto_approve_request": re.compile(
        r"(?i)\bauto[- ]?(approve|reply|execute)\b.{0,20}\bwithout\b.{0,20}\breview\b"
    ),
}


class InjectionNode:
    """Prompt-injection screen — spec §6.2 node `detect_inject`.

    A hit routes straight to `emit_signals`, so no further token is spent on
    a ticket that is trying to talk to the model rather than to support.

    Read-only after __init__; one instance is shared across FastAPI's
    threadpool.
    """

    def __init__(self, *, patterns: dict[str, re.Pattern] | None = None) -> None:
        # A pattern set, not a number — it belongs in code like patterns.py's
        # PII regexes, not in an env var. The parameter exists so a test can
        # narrow it, not so deployments can diverge.
        self._patterns = patterns if patterns is not None else DEFAULT_PATTERNS

    def __call__(self, state: TriageState) -> dict:
        text = f"{state['ticket'].subject_masked}\n{state['ticket'].body_masked}"
        matched = [name for name, pattern in self._patterns.items() if pattern.search(text)]
        verdict: InjectionVerdict = {"detected": bool(matched), "matched_patterns": matched}
        return {"injection": verdict}
