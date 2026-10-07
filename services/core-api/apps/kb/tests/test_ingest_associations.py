"""
Re-ingesting an article refreshes its associations (ADR-0018). Edges drawn
from the old text must not outlive it: an `entity_graph` edge extracted
from a paragraph that has since been deleted would keep pulling the page
into tickets it no longer answers. The article runs on its authored links
until the next build.
"""

from __future__ import annotations

import pytest

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation

pytestmark = pytest.mark.django_db


def _article(slug: str, body: str) -> KbArticle:
    return KbArticle.objects.create_and_ingest(
        slug=slug, title=slug, body=body, category="access", risk_tier="medium"
    )


def _edge(source: KbArticle, target: KbArticle, kind: str) -> None:
    KbArticleAssociation.objects.create(
        source_article=source, target_article=target, source=kind, score=1.0, build_id="t"
    )


def _sources(**filters: object) -> set[str]:
    return set(KbArticleAssociation.objects.filter(**filters).values_list("source", flat=True))


def test_reingest_drops_extracted_edges_both_ways_and_rereads_authored_links():
    article = _article("verify", "old text")
    other = _article("prod", "production access")
    for a, slug in ((article, "verify"), (other, "prod")):
        a.source_url = f"https://docs.aws.amazon.com/ses/{slug}.html"
        a.save(update_fields=["source_url"])
    for kind in (AssociationSource.ENTITY_GRAPH, AssociationSource.EMBEDDING_NEIGHBOUR):
        _edge(article, other, kind)
        _edge(other, article, kind)
    # An edge between two other articles is none of this article's business.
    third = _article("smtp", "smtp credentials")
    _edge(other, third, AssociationSource.ENTITY_GRAPH)

    article.body = "See [prod](prod.md)."
    article.save(update_fields=["body"])
    article.ingest()

    # No entity_graph edge survives. The neighbour source had been built, so
    # the article's own neighbours were recomputed from its new vectors;
    # other articles' edges to it wait for their next build.
    assert _sources(source_article=article) == {
        AssociationSource.AUTHORED_LINK,
        AssociationSource.EMBEDDING_NEIGHBOUR,
    }
    assert _sources(target_article=article) == set()
    assert _sources(source_article=other, target_article=third) == {AssociationSource.ENTITY_GRAPH}


def test_hard_deleting_an_article_leaves_no_associations():
    article = _article("verify", "text")
    other = _article("prod", "production access")
    _edge(article, other, AssociationSource.ENTITY_GRAPH)
    _edge(other, article, AssociationSource.ENTITY_GRAPH)

    article.delete()

    assert not KbArticleAssociation.objects.exists()


def test_an_unchanged_reload_touches_no_associations():
    """`upsert_from_source` skips `ingest` when nothing changed, so a reload
    must not drop a built `entity_graph` edge."""
    fields = dict(
        body="text",
        category="access",
        risk_tier="medium",
        title="Verify",
    )
    article, _ = KbArticle.objects.upsert_from_source(
        slug="verify", source_url="https://docs.aws.amazon.com/ses/verify.html", **fields
    )
    other = _article("prod", "production access")
    _edge(article, other, AssociationSource.ENTITY_GRAPH)

    KbArticle.objects.upsert_from_source(
        slug="verify", source_url="https://docs.aws.amazon.com/ses/verify.html", **fields
    )

    assert _sources(source_article=article) == {AssociationSource.ENTITY_GRAPH}
