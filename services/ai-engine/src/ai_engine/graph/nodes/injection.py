"""
Injection detector — spec §6.2 `detect_inject`. Runs FIRST, before any
retrieval or LLM cost. Attachments are fully untrusted (spec §5.2) and never
fetched, so nothing from one reaches the prompt.
"""

from __future__ import annotations

import re
from enum import StrEnum

from ai_engine.core.node import BaseNode
from ai_engine.core.state import TriageState

PATTERNS: dict[str, re.Pattern] = {
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


class InjectionNode(BaseNode):
    """Prompt-injection screen. A hit routes straight to `EmitSignalsNode`,
    spending no further tokens.
    """

    class Outcome(StrEnum):
        INJECTION_DETECTED = "InjectionDetected"
        INJECTION_CLEAR = "InjectionClear"

    def __call__(self, state: TriageState) -> dict:
        text = f"{state.ticket.subject_masked}\n{state.ticket.body_masked}"
        matched = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
        return {"injection_detected": bool(matched), "injection_matched_patterns": matched}

    def decide(self, state: TriageState) -> InjectionNode.Outcome:
        if state.injection_detected:
            return self.Outcome.INJECTION_DETECTED
        return self.Outcome.INJECTION_CLEAR
