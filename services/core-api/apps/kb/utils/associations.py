"""
Article associations for link expansion (ADR-0014 decision 1, ADR-0018):
the pure parts. Pulling links out of chunk text, with no database access;
the rows are written by
`KbArticleAssociation.objects`.

`resolve_link` and the link pattern are a port of ai-engine's
`candidate_pool/links.py`, which extracted links per ticket before the
table existed. The two must resolve the same URLs, or moving the work to
ingest time would change which pages expansion follows. ai-engine's copy
stays only until the parity check has run (ADR-0018).
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
    """The page `href` points to, as a `source_url` would spell it. The
    snapshot's relative links name its Markdown files (`foo.md`) where
    `source_url` names the published page (`foo.html`); fragments and
    trailing slashes don't change the page."""

    url = urldefrag(urljoin(base_url, href))[0].rstrip("/")
    return url[: -len(".md")] + ".html" if url.endswith(".md") else url


def linked_urls(base_url: str, contents: Iterable[str]) -> dict[str, str]:
    """Every page the chunk texts link to, in document order, each once:
    resolved URL -> the first href that named it. `contents` must be the
    article's chunks in `chunk_index` order, the text ai-engine's regex read,
    so document order is the same."""

    # A dict as an ordered set: one page links to 198 others.
    urls: dict[str, str] = {}
    for content in contents:
        for href in _LINK.findall(content):
            urls.setdefault(resolve_link(base_url, href), href)
    return urls


def link_scores(
    urls: Mapping[str, str], article_by_url: Mapping[str, uuid.UUID], *, own_id: uuid.UUID
) -> list[tuple[uuid.UUID, float, str]]:
    """`(target, score, href)` for each link that resolves to another
    article in the KB, active or not (the read filters inactive ones).
    `score = 1 / (1 + position)` among those targets, so ordering by score
    is document order. Links out of the KB and to the article itself are
    skipped; they would use up a position the cap counts."""

    rows: list[tuple[uuid.UUID, float, str]] = []
    seen: set[uuid.UUID] = set()
    for url, href in urls.items():
        target = article_by_url.get(url)
        if target is None or target == own_id or target in seen:
            continue
        seen.add(target)
        rows.append((target, 1 / (1 + len(rows)), href))
    return rows


def build_id(source: str, *parts: str) -> str:
    """What made a row, e.g. `authored_link:2026-10-07`."""

    return ":".join([source, *parts, datetime.now(UTC).date().isoformat()])
