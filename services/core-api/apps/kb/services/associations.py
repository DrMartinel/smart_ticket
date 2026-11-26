"""
Pulls the `authored_link` associations out of chunk text (ADR-0014
decision 1, ADR-0018).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from urllib.parse import urldefrag, urljoin

# The target of a Markdown link: `[text](target)` or `[text](target "title")`.
_LINK = re.compile(r"\]\(([^)\s]+)")


def resolve_link(base_url: str, href: str) -> str:
    """Resolves `href` to its page as `source_url` spells it: `.md` as
    `.html`, without a fragment or a trailing slash."""

    url = urldefrag(urljoin(base_url, href))[0].rstrip("/")
    return url[: -len(".md")] + ".html" if url.endswith(".md") else url


def linked_urls(base_url: str, contents: Iterable[str]) -> dict[str, str]:
    """Maps each page the chunk texts link to, in document order, to the
    first href that named it."""

    urls: dict[str, str] = {}
    for content in contents:
        for href in _LINK.findall(content):
            urls.setdefault(resolve_link(base_url, href), href)
    return urls


def link_scores(
    urls: Mapping[str, str], article_by_url: Mapping[str, uuid.UUID], *, own_id: uuid.UUID
) -> list[tuple[uuid.UUID, float, str]]:
    """Scores each link to another KB article by its document position,
    first highest."""

    rows: list[tuple[uuid.UUID, float, str]] = []
    seen: set[uuid.UUID] = set()
    for url, href in urls.items():
        target = article_by_url.get(url)
        if target is None or target == own_id or target in seen:
            continue
        seen.add(target)
        rows.append((target, 1 / (1 + len(rows)), href))
    return rows


def build_id(source: str) -> str:
    """Names the build that made a row, e.g. `authored_link:2026-10-07`."""

    return f"{source}:{datetime.now(UTC).date().isoformat()}"
