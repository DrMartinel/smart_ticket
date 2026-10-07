"""
`embedding_neighbour` associations (ADR-0018): the no-LLM control that
`entity_graph` must beat. Article centroids come from vectors already in
`kb_chunks`, so a bug here doesn't fail loudly, it just makes the control
look worse (or better) than it is and skews the comparison.
"""

from __future__ import annotations

import uuid
from io import StringIO

import numpy as np
import pytest
from django.core.management import call_command

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation, KbChunk
from apps.kb.utils.associations import nearest_neighbours, normalised


def test_nearest_neighbours_rank_by_cosine_and_never_pick_self():
    ids = [uuid.UUID(int=i) for i in (1, 2, 3)]
    vectors = normalised(np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]))

    rows = nearest_neighbours(ids, vectors, k=1)

    assert [(s.int, t.int) for s, t, _ in rows] == [(1, 2), (2, 1), (3, 2)]


def test_equal_similarities_break_on_target_id_so_rebuilds_agree():
    ids = [uuid.UUID(int=i) for i in (3, 1, 2)]
    vectors = normalised(np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]))

    rows = nearest_neighbours(ids, vectors, k=2, among=[0])

    assert [t.int for _, t, _ in rows] == [1, 2]


def test_a_zero_vector_stays_zero_instead_of_nan():
    assert not np.isnan(normalised(np.array([[0.0, 0.0], [3.0, 4.0]]))).any()


def _article(slug: str, vectors: list[list[float]], *, active: bool = True) -> KbArticle:
    article = KbArticle.objects.create(
        slug=slug, title=slug, body="x", category="access", is_active=active
    )
    for i, v in enumerate(vectors):
        KbChunk.objects.create(
            article=article,
            chunk_index=i,
            content=f"{slug} {i}",
            token_count=1,
            embedding=v + [0.0] * (1024 - len(v)),
        )
    return article


def _neighbours(article: KbArticle) -> list[str]:
    return list(
        KbArticleAssociation.objects.filter(
            source_article=article, source=AssociationSource.EMBEDDING_NEIGHBOUR
        )
        .order_by("-score")
        .values_list("target_article__slug", flat=True)
    )


@pytest.mark.django_db
def test_rebuild_uses_the_centroid_keeps_inactive_targets_and_skips_unembedded_articles():
    """The centroid is the mean of an article's chunks, so a long page is
    one point, not one vote per chunk. An inactive article is still stored
    (the read filters it); one with no vectors can't be placed at all."""
    seed = _article("seed", [[1.0, 0.0]])
    near = _article("near", [[1.0, 0.2], [1.0, -0.2]], active=False)
    _article("far", [[0.0, 1.0]])
    KbArticle.objects.create(slug="unembedded", title="u", body="x", category="access")

    written = KbArticleAssociation.objects.rebuild_embedding_neighbours(k=1)

    assert written == 3
    assert _neighbours(seed) == ["near"]
    assert _neighbours(near) == ["seed"]
    assert not KbArticleAssociation.objects.filter(target_article__slug="unembedded").exists()


@pytest.mark.django_db
def test_build_associations_command_uses_k_from_thresholds(settings):
    seed = _article("seed", [[1.0, 0.0]])
    _article("a", [[1.0, 0.1]])
    _article("b", [[1.0, 0.3]])
    settings.THRESHOLDS = settings.THRESHOLDS.model_copy(
        update={
            "associations": settings.THRESHOLDS.associations.model_copy(
                update={"embedding_neighbour_k": 2}
            )
        }
    )

    call_command("build_associations", source="embedding_neighbour", stdout=StringIO())

    assert _neighbours(seed) == ["a", "b"]


@pytest.mark.django_db
def test_once_neighbours_are_built_a_reingested_article_gets_fresh_ones():
    """Re-ingesting drops the article's old neighbour rows both ways; if the
    source has been built, its own are recomputed from the new vectors
    rather than left missing until the next full build."""
    KbArticle.objects.create_and_ingest(
        slug="one", title="one", body="first", category="access", risk_tier="medium"
    )
    article = KbArticle.objects.create_and_ingest(
        slug="two", title="two", body="second", category="access", risk_tier="medium"
    )
    KbArticleAssociation.objects.rebuild_embedding_neighbours(k=5)

    article.body = "second, rewritten"
    article.save(update_fields=["body"])
    article.ingest()

    assert _neighbours(article) == ["one"]
