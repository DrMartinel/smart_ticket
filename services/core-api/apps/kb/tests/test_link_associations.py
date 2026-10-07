"""
`authored_link` associations (ADR-0018): links read from chunk text at
ingest time instead of per ticket in ai-engine. The port must resolve the
same pages ai-engine's regex did, in the same order, or moving the work
would quietly change which pages link expansion follows. Rows are kept
for inactive targets, because ai-engine's read filters them: a
reactivated page must come back without a rebuild.
"""

from __future__ import annotations

import uuid

import pytest

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation, KbChunk
from apps.kb.utils.associations import link_scores, linked_urls, resolve_link

BASE = "https://docs.aws.amazon.com/ses/latest/dg/verify.html"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        (
            "request-production-access.md",
            "https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html",
        ),
        (
            "request-production-access.html#sandbox",
            "https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html",
        ),
        (
            "https://docs.aws.amazon.com/iam/latest/ug/mfa.html/",
            "https://docs.aws.amazon.com/iam/latest/ug/mfa.html",
        ),
        ("../../../iam/latest/ug/mfa.md", "https://docs.aws.amazon.com/iam/latest/ug/mfa.html"),
    ],
    ids=["md-to-html", "fragment", "trailing-slash", "relative-up"],
)
def test_resolve_link_names_the_page_as_source_url_spells_it(href, expected):
    assert resolve_link(BASE, href) == expected


def test_linked_urls_keep_document_order_across_chunks_and_each_page_once():
    urls = linked_urls(
        BASE, ["See [b](b.md) and [a](a.md).", "Again [b](b.html#x), then [c](c.md)."]
    )

    assert [u.rsplit("/", 1)[1] for u in urls] == ["b.html", "a.html", "c.html"]
    assert urls[resolve_link(BASE, "b.md")] == "b.md"  # the first href that named it


def test_link_scores_follow_document_order_and_skip_self_and_out_of_kb_links():
    """The cap in ai-engine counts pages a link resolved to; a link out of
    the KB or to the article itself must not use up a position."""
    own, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    urls = {"self": "s", "outside": "o", "first": "f", "second": "x", "first-again": "f2"}
    by_url = {"self": own, "first": first, "second": second, "first-again": first}

    rows = link_scores(urls, by_url, own_id=own)

    assert [(t, s) for t, s, _ in rows] == [(first, 1.0), (second, 0.5)]


def _article(slug: str, body: str, *, active: bool = True) -> KbArticle:
    article = KbArticle.objects.create(
        slug=slug,
        title=slug,
        body=body,
        category="access",
        source_url=f"https://docs.aws.amazon.com/ses/latest/dg/{slug}.html",
        is_active=active,
    )
    KbChunk.objects.create(article=article, chunk_index=0, content=body, token_count=1)
    return article


def _targets(article: KbArticle) -> list[str]:
    return list(
        KbArticleAssociation.objects.filter(
            source_article=article, source=AssociationSource.AUTHORED_LINK
        )
        .order_by("-score")
        .values_list("target_article__slug", flat=True)
    )


@pytest.mark.django_db
def test_rebuild_stores_inactive_targets_and_skips_pages_outside_the_kb():
    seed = _article("verify", "[gone](retired.md) [out](https://example.com/x) [prod](prod.md)")
    _article("retired", "old page", active=False)
    _article("prod", "production access")

    KbArticleAssociation.objects.rebuild_authored_links()

    assert _targets(seed) == ["retired", "prod"]


@pytest.mark.django_db
def test_a_full_rebuild_replaces_the_source_and_leaves_other_sources_alone():
    seed = _article("verify", "[prod](prod.md)")
    prod = _article("prod", "production access")
    KbArticleAssociation.objects.create(
        source_article=seed,
        target_article=prod,
        source=AssociationSource.ENTITY_GRAPH,
        score=6.4,
        build_id="t",
    )
    KbArticleAssociation.objects.rebuild_authored_links()
    seed.chunks.update(content="no links any more")

    KbArticleAssociation.objects.rebuild_authored_links()

    assert _targets(seed) == []
    assert KbArticleAssociation.objects.filter(source=AssociationSource.ENTITY_GRAPH).count() == 1


@pytest.mark.django_db
def test_build_associations_command_rebuilds_authored_links():
    from io import StringIO

    from django.core.management import call_command

    seed = _article("verify", "[prod](prod.md)")
    _article("prod", "production access")

    call_command("build_associations", source="authored_link", stdout=StringIO())

    assert _targets(seed) == ["prod"]
