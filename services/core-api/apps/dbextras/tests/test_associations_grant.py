"""
ai-engine's read-only role on `kb_article_associations` (ADR-0018,
infra/migrations/sql/0006), against the real Dockerized Postgres. Link
expansion reads the table as `ai_engine_ro`; a missing grant would fail
only on the first ticket that expanded, and a write grant would end
ADR-0004's boundary, which Postgres alone enforces.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from django.db.backends.utils import CursorWrapper
from django.db import DatabaseError, connection, transaction

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation

pytestmark = pytest.mark.django_db


@pytest.fixture
def association() -> KbArticleAssociation:
    def article(slug: str) -> KbArticle:
        return KbArticle.objects.create(slug=slug, title=slug, body="x", category="access")

    return KbArticleAssociation.objects.create(
        source_article=article("ses.verify"),
        target_article=article("ses.production-access"),
        source=AssociationSource.ENTITY_GRAPH,
        score=6.38,
        evidence=["SES Sandbox"],
        build_id="test",
    )


@contextmanager
def _as_ai_engine() -> Iterator[CursorWrapper]:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE ai_engine_ro")
        try:
            yield cursor
        finally:
            cursor.execute("RESET ROLE")


def test_ai_engine_role_can_read_associations(association):
    with _as_ai_engine() as cursor:
        cursor.execute("SELECT source, score FROM kb_article_associations")

        assert cursor.fetchall() == [("entity_graph", 6.38)]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO kb_article_associations (id, source_article_id, target_article_id, source,"
        " score, evidence, reviewed, build_id) SELECT gen_random_uuid(), target_article_id,"
        " source_article_id, source, score, evidence, reviewed, build_id"
        " FROM kb_article_associations",
        "UPDATE kb_article_associations SET reviewed = true",
        "DELETE FROM kb_article_associations",
    ],
    ids=["insert", "update", "delete"],
)
def test_ai_engine_role_cannot_write_associations(association, sql):
    with _as_ai_engine() as cursor:
        # The savepoint rolls back the failed statement, so RESET ROLE runs
        # in a usable transaction.
        with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
            cursor.execute(sql)
