"""
Cuts a page's text into sections for the model.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)
_SEPARATORS = ("\n\n", "\n", " ")


class SectionSplitter:
    """Cuts text into sections of at most `max_tokens`, at headings first."""

    def __init__(
        self, *, max_tokens: int, count: Callable[[str], int], strip_links: bool = False
    ) -> None:
        self._max_tokens = max_tokens
        self._count = count
        self._strip_links = strip_links

    @staticmethod
    def strip_links(text: str) -> str:
        """Replaces each Markdown link with its text."""

        return _LINK.sub(r"\1", text)

    def split(self, text: str) -> list[str]:
        """Cuts `text` into sections, in page order."""

        if self._strip_links:
            text = self.strip_links(text)
        blocks = [b for b in self._split_at_headings(text) if b.strip()]
        return self._pack(blocks, "\n", depth=0)

    @staticmethod
    def _split_at_headings(text: str) -> list[str]:
        starts = [m.start() for m in _HEADING.finditer(text)]
        if not starts or starts[0] != 0:
            starts.insert(0, 0)
        return [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]

    def _pack(self, units: list[str], sep: str, *, depth: int) -> list[str]:
        out: list[str] = []
        current: list[str] = []
        size = 0
        sep_size = self._count(sep) if sep.strip() else 1
        for unit in units:
            n = self._count(unit)
            if n > self._max_tokens:
                if current:
                    out.append(sep.join(current))
                    current, size = [], 0
                out.extend(self._split_unit(unit, depth))
                continue
            if current and size + sep_size + n > self._max_tokens:
                out.append(sep.join(current))
                current, size = [], 0
            size += (sep_size if current else 0) + n
            current.append(unit)
        if current:
            out.append(sep.join(current))
        return [s for s in out if s.strip()]

    def _split_unit(self, unit: str, depth: int) -> list[str]:
        """Splits one piece over budget at the next finer separator."""

        if depth >= len(_SEPARATORS):
            return [unit]
        sep = _SEPARATORS[depth]
        parts = [p for p in unit.split(sep) if p]
        if len(parts) == 1:
            return self._split_unit(unit, depth + 1)
        return self._pack(parts, sep, depth=depth + 1)
