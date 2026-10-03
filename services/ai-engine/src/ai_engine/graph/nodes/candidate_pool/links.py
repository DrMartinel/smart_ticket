"""
Link expansion (ADR-0014 decisions 1-2, ADR-0015): the pages an article
links to, and their chunks nearest the ticket. A page that describes the
symptom often links to the page with the fix; this brings that page into
the pool the cross-encoder scores, whatever its wording.

Links are read from chunk text per request, not from a table: Markdown
links, resolved against the article's `source_url` and matched exactly.
ADR-0014's associations table, written at ingestion, would replace
`linked_article_ids` without changing its contract.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urldefrag, urljoin

from sqlalchemy import func, select

from ai_engine.core.db.client import db
from ai_engine.core.db.tables import KbArticle, KbChunk
from ai_engine.graph.state import Candidate

# The target of a Markdown link: `[text](target)` or `[text](target "title")`.
_LINK = re.compile(r"\]\(([^)\s]+)")


def resolve_link(base_url: str, href: str) -> str:
    """The page `href` points to, as a `source_url` would spell it. The
    snapshot's relative links name its Markdown files (`foo.md`) where
    `source_url` names the published page (`foo.html`); fragments and
    trailing slashes don't change the page."""

    url = urldefrag(urljoin(base_url, href))[0].rstrip("/")
    return url[: -len(".md")] + ".html" if url.endswith(".md") else url


def linked_article_ids(seed_ids: list[uuid.UUID], *, max_per_seed: int) -> list[uuid.UUID]:
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


def nearest_chunks(
    article_ids: list[uuid.UUID],
    query_embedding: list[float],
    *,
    per_article: int,
) -> list[Candidate]:
    """Each article's `per_article` chunks nearest the query embedding, in
    one query. Pages are long; their best chunks for this ticket are the
    ones worth scoring."""

    if not article_ids:
        return []
    distance = KbChunk.embedding.cosine_distance(query_embedding)
    ranked = (
        select(
            KbChunk.id,
            KbChunk.article_id,
            KbArticle.slug,
            KbChunk.content,
            func.row_number()
            .over(partition_by=KbChunk.article_id, order_by=distance)
            .label("rank"),
        )
        .join(KbArticle, KbArticle.id == KbChunk.article_id)
        .where(KbChunk.article_id.in_(article_ids), KbChunk.embedding.is_not(None))
        .subquery()
    )
    rows = db.all(
        select(ranked.c.id, ranked.c.article_id, ranked.c.slug, ranked.c.content)
        .where(ranked.c.rank <= per_article)
        .order_by(ranked.c.article_id, ranked.c.rank)
    )
    return [
        Candidate(chunk_id=cid, article_id=aid, article_slug=slug, content=content)
        for cid, aid, slug, content in rows
    ]


def article_titles(article_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Titles for Jev, which sees each passage with its page title."""

    if not article_ids:
        return {}
    return {
        article_id: title
        for article_id, title in db.all(
            select(KbArticle.id, KbArticle.title).where(KbArticle.id.in_(article_ids))
        )
    }
