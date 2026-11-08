"""
The prompt-injection patterns, shared by the triage graph's injection guard
and the agent graph's screens (the user's message and untrusted tool results).
"""

from __future__ import annotations

import re

PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions_en": re.compile(
        r"(?i)\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all)\b.{0,30}\b(instructions?|rules?|prompt)\b"
    ),
    "ignore_instructions_vi": re.compile(
        r"(?i)\b(bỏ qua|quên)\b.{0,20}\b(hướng dẫn|chỉ dẫn|quy tắc|lệnh)\b.{0,20}\b(trên|phía trên|trước đó)\b"
    ),
    "role_override_en": re.compile(
        r"(?i)\byou are now\b|\bact as\b|\bnew system prompt\b|\bDAN mode\b"
    ),
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


def matches(text: str) -> list[str]:
    """The names of the patterns `text` matches."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]
