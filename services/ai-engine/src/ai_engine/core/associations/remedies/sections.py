"""
A page's text cut into sections for the model: whole Markdown headings
first, so a problem and the sentence pointing to its fix stay together,
then paragraphs, lines and words for anything still too long.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# [text](target) -> text. Images (![alt](src)) keep their alt text.
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)

# Finer and finer separators for a piece over budget: paragraphs, lines
# (a long table is one paragraph), words.
_SEPARATORS = ("\n\n", "\n", " ")


def strip_links(text: str) -> str:
    """Markdown links replaced by their text: what the prose names, never
    the URL it points to (the policy's `strip_links`)."""

    return _LINK.sub(r"\1", text)


def split_sections(text: str, *, max_tokens: int, count: Callable[[str], int]) -> list[str]:
    """Sections of about `max_tokens` at most (by `count`), in page order,
    none empty. Consecutive headed blocks are packed together while they fit.

    Each unit is counted once and the counts are summed, so a page of
    ~180k tokens is cut in one pass; joining can merge a token or two at a
    boundary, which only makes a section slightly shorter than counted."""

    blocks = [b for b in _split_at_headings(text) if b.strip()]
    return _pack(blocks, "\n", max_tokens, count, depth=0)


def _split_at_headings(text: str) -> list[str]:
    starts = [m.start() for m in _HEADING.finditer(text)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    return [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]


def _pack(
    units: list[str], sep: str, max_tokens: int, count: Callable[[str], int], *, depth: int
) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    size = 0
    sep_size = count(sep) if sep.strip() else 1
    for unit in units:
        n = count(unit)
        if n > max_tokens:
            if current:
                out.append(sep.join(current))
                current, size = [], 0
            out.extend(_split_unit(unit, max_tokens, count, depth))
            continue
        if current and size + sep_size + n > max_tokens:
            out.append(sep.join(current))
            current, size = [], 0
        size += (sep_size if current else 0) + n
        current.append(unit)
    if current:
        out.append(sep.join(current))
    return [s for s in out if s.strip()]


def _split_unit(unit: str, max_tokens: int, count: Callable[[str], int], depth: int) -> list[str]:
    """One piece over budget, split at the next finer separator. A single
    word over budget (never seen in the KB) is kept whole rather than cut."""

    if depth >= len(_SEPARATORS):
        return [unit]
    sep = _SEPARATORS[depth]
    parts = [p for p in unit.split(sep) if p]
    if len(parts) == 1:
        return _split_unit(unit, max_tokens, count, depth + 1)
    return _pack(parts, sep, max_tokens, count, depth=depth + 1)
