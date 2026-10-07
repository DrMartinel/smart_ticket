"""
Text chunking for KB ingestion. Pure functions over strings; the ingestion
itself is `KbArticle.ingest()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHUNK_TARGET_TOKENS = 250

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
# AWS docs Markdown carries an HTML anchor under most headings
# (`<a name="welcome"></a>`). It is link-target plumbing, not content, and
# would otherwise land in chunks, embeddings and BM25 terms.
_ANCHOR_LINE = re.compile(r'^\s*<a name="[^"]*"></a>\s*$')


@dataclass(frozen=True)
class Chunk:
    section_title: str | None
    content: str


def rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def clean_markdown(text: str) -> str:
    """Drops anchor-only lines and surrounding blank lines. Everything else
    is kept verbatim, because `verbatim_quote` is checked as an exact
    substring of the stored chunk text (spec §6.4)."""

    lines = [line for line in text.splitlines() if not _ANCHOR_LINE.match(line)]
    return "\n".join(lines).strip()


def chunk_body(body: str) -> list[str]:
    """Paragraph-aware chunking targeting ~CHUNK_TARGET_TOKENS tokens per
    chunk. Simple and deterministic on purpose — retrieval quality here
    depends far more on chunk *boundaries respecting paragraphs* than on a
    fancier splitter."""

    return _pack(_blocks(body.splitlines())) or [body]


def chunk_sections(body: str) -> list[Chunk]:
    """Splits Markdown at headings, then packs each section's paragraphs
    with the same rule as `chunk_body`. Each chunk records the heading it
    sits under, so retrieval can show *where* in a long AWS guide page a
    passage came from. A body with no headings gives exactly `chunk_body`'s
    chunks, with `section_title=None`.

    Lines inside fenced code blocks are never treated as headings or
    paragraph breaks: a shell comment (`# restart the agent`) is not a
    section, and a code sample split in half is useless as a quote. The one
    exception is a block over the chunk target by itself, split at line
    breaks by `_split_long` so it can be embedded at all."""

    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_fence = False
    for line in body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading:
            sections.append((heading.group(2), [line]))
        else:
            sections[-1][1].append(line)

    chunks = [
        Chunk(section_title=title, content=content)
        for title, lines in sections
        for content in _pack(_blocks(lines))
    ]
    return chunks or [Chunk(section_title=None, content=body)]


def _blocks(lines: list[str]) -> list[str]:
    """Blank-line-separated paragraphs, keeping each fenced code block whole."""

    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _pack(paragraphs: list[str], sep: str = "\n\n") -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for p in (piece for paragraph in paragraphs for piece in _split_long(paragraph)):
        p_tokens = rough_token_count(p)
        if current and current_tokens + p_tokens > CHUNK_TARGET_TOKENS:
            chunks.append(sep.join(current))
            current, current_tokens = [], 0
        current.append(p)
        current_tokens += p_tokens
    if current:
        chunks.append(sep.join(current))
    return chunks


def _split_long(block: str) -> list[str]:
    """A block over the target, split at line breaks, and a line still over
    it into word windows. A Markdown table has no blank lines, so without
    this a whole table becomes one chunk: the AWS docs have tables of
    300,000+ characters, far past the embedder's context, and one of them
    stops `load_demo_kb` with a 502 from `/v1/embed`. Table rows, list items
    and code lines stay whole wherever one fits in the target."""

    if rough_token_count(block) <= CHUNK_TARGET_TOKENS:
        return [block]
    lines = block.splitlines()
    if len(lines) > 1:
        return _pack(lines, sep="\n")
    words = block.split()
    return [
        " ".join(words[i : i + CHUNK_TARGET_TOKENS])
        for i in range(0, len(words), CHUNK_TARGET_TOKENS)
    ]
