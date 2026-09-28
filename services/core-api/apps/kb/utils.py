"""
Text chunking for KB ingestion. Pure functions over strings; the ingestion
itself is `KbArticle.ingest()`.
"""

from __future__ import annotations

import re

CHUNK_TARGET_TOKENS = 250


def rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def chunk_body(body: str) -> list[str]:
    """Paragraph-aware chunking targeting ~CHUNK_TARGET_TOKENS tokens per
    chunk. Simple and deterministic on purpose — retrieval quality here
    depends far more on chunk *boundaries respecting paragraphs* than on a
    fancier splitter."""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for p in paragraphs:
        p_tokens = rough_token_count(p)
        if current and current_tokens + p_tokens > CHUNK_TARGET_TOKENS:
            chunks.append("\n\n".join(current))
            current, current_tokens = [], 0
        current.append(p)
        current_tokens += p_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [body]
