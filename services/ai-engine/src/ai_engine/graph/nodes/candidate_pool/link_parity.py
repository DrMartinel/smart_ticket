"""
The regex link extraction link expansion used before ADR-0018, kept ONLY for
the parity check: for every active article, the table path
(`links.linked_article_ids` with `ASSOCIATION_SOURCE=authored_link`) must
return the same pages as this one did. Delete this module once that check
has been run and recorded in evals/HISTORY.md (ADR-0018, *Before this is
accepted* #1). Nothing on the request path imports it.

Run from the repo root against the loaded demo KB, with ai-engine's `.env`:

    uv run python -m ai_engine.graph.nodes.candidate_pool.link_parity
"""

from __future__ import annotations

import re
import sys
import uuid
from urllib.parse import urldefrag, urljoin

from sqlalchemy import select

from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle, KbChunk
from ai_engine.graph.nodes.candidate_pool.links import linked_article_ids

# The target of a Markdown link: `[text](target)` or `[text](target "title")`.
_LINK = re.compile(r"\]\(([^)\s]+)")


def resolve_link(base_url: str, href: str) -> str:
    """The page `href` points to, as a `source_url` would spell it. The
    snapshot's relative links name its Markdown files (`foo.md`) where
    `source_url` names the published page (`foo.html`); fragments and
    trailing slashes don't change the page."""

    url = urldefrag(urljoin(base_url, href))[0].rstrip("/")
    return url[: -len(".md")] + ".html" if url.endswith(".md") else url


def linked_article_ids_from_text(
    seed_ids: list[uuid.UUID], *, max_per_seed: int
) -> list[uuid.UUID]:
    """Active articles linked from `seed_ids`, seeds first to last, each
    seed's links in document order, at most `max_per_seed` per seed, each
    article once. A seed's link to itself is skipped; a link to another
    seed or to a fused candidate is kept, since that page may have better
    chunks than the ones retrieved (the caller de-duplicates chunks)."""

    if not seed_ids:
        return []
    base = {
        article_id: url
        for article_id, url in db.all(
            select(KbArticle.id, KbArticle.source_url).where(KbArticle.id.in_(seed_ids))
        )
    }
    chunks = db.all(
        select(KbChunk.article_id, KbChunk.content)
        .where(KbChunk.article_id.in_(seed_ids))
        .order_by(KbChunk.article_id, KbChunk.chunk_index)
    )

    # Dicts as ordered sets: document order, each URL once. One page links
    # to 198 others, so list membership would be quadratic.
    urls_by_seed: dict[uuid.UUID, dict[str, None]] = {seed: {} for seed in seed_ids}
    for article_id, content in chunks:
        base_url = base.get(article_id)
        if not base_url:
            continue
        for href in _LINK.findall(content):
            urls_by_seed[article_id].setdefault(resolve_link(base_url, href))

    wanted = {url for urls in urls_by_seed.values() for url in urls}
    if not wanted:
        return []
    by_url = {
        url: article_id
        for url, article_id in db.all(
            select(KbArticle.source_url, KbArticle.id).where(
                KbArticle.source_url.in_(wanted), KbArticle.is_active.is_(True)
            )
        )
        if url is not None
    }

    linked: list[uuid.UUID] = []
    for seed in seed_ids:
        # The cap counts pages a link resolved to, not raw links: a link
        # out of the KB costs nothing and shouldn't use up the allowance.
        targets = [by_url[u] for u in urls_by_seed[seed] if u in by_url and by_url[u] != seed]
        for target in list(dict.fromkeys(targets))[:max_per_seed]:
            if target not in linked:
                linked.append(target)
    return linked


def main() -> int:
    """Compares the two paths for every active article, one seed at a time,
    at the production cap. Prints each difference; exits 1 if there is any."""

    if settings.association_source != "authored_link":
        print("set ASSOCIATION_SOURCE=authored_link: parity is against authored links")
        return 2
    cap = settings.link_expansion_max_links_per_seed
    seeds = [row[0] for row in db.all(select(KbArticle.id).where(KbArticle.is_active.is_(True)))]
    differences = 0
    for seed in seeds:
        old = linked_article_ids_from_text([seed], max_per_seed=cap)
        new = linked_article_ids([seed], max_per_seed=cap)
        if old != new:
            differences += 1
            print(f"{seed}: regex {old} != table {new}")
    print(f"{len(seeds)} active articles, {differences} differ")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
