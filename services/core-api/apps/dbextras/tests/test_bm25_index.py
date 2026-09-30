"""
The pg_search BM25 index (ADR-0013, infra/migrations/sql/0005), against the
real Dockerized Postgres. Fakes can't catch any of this: whether the
extension is loaded, whether the index follows writes without the old
trigger, and whether ai-engine's read-only role can query it without being
granted anything that would let it write (ADR-0004).
"""

from __future__ import annotations

import pytest

from django.db import DatabaseError, connection, transaction

from apps.kb.models import KbArticle, KbChunk

pytestmark = pytest.mark.django_db

# The query shape ai-engine's bm25_search sends.
_BM25_QUERY = """
    SELECT a.slug
    FROM kb_chunks c JOIN kb_articles a ON a.id = c.article_id
    WHERE c.content ||| %s OR c.section_title ||| %s
    ORDER BY pdb.score(c.id) DESC
"""


@pytest.fixture
def chunk() -> KbChunk:
    article = KbArticle.objects.create(
        slug="guardduty.compromised-ec2", title="t", body="x", category="security"
    )
    return KbChunk.objects.create(
        article=article,
        chunk_index=0,
        content="Remediating a potentially compromised Amazon EC2 instance",
        section_title="GuardDuty findings",
        token_count=8,
    )


def _search(cursor, text: str) -> list[str]:
    cursor.execute(_BM25_QUERY, [text, text])
    return [row[0] for row in cursor.fetchall()]


def test_ai_engine_role_can_run_bm25_but_still_cannot_write(chunk):
    """BM25 needs pg_search's `pdb` schema. If making it work ever needs a
    grant, it must be USAGE only: ai_engine_ro writing to kb_chunks would end
    ADR-0004's boundary, which is enforced by Postgres and nothing else."""

    with connection.cursor() as cursor:
        cursor.execute("SET ROLE ai_engine_ro")
        try:
            assert _search(cursor, "compromised instance") == ["guardduty.compromised-ec2"]
            with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
                cursor.execute("DELETE FROM kb_chunks")
        finally:
            cursor.execute("RESET ROLE")


def test_a_new_chunk_is_searchable_without_a_trigger(chunk):
    """The old `tsv` column needed a trigger, so a write path that bypassed
    it left chunks unsearchable. The BM25 index must follow every insert by
    itself, and match on SOME of the words: a ticket rarely contains all of
    a chunk's."""

    with connection.cursor() as cursor:
        assert _search(cursor, "my EC2 box looks compromised, what now") == [
            "guardduty.compromised-ec2"
        ]


def test_english_stemming_matches_inflected_forms(chunk):
    """The index uses the English stemmer (ADR-0013): "remediate" must find
    "Remediating". Losing the tokenizer config would pass every other test
    and quietly cost recall."""

    with connection.cursor() as cursor:
        assert _search(cursor, "remediate") == ["guardduty.compromised-ec2"]


def test_the_tsv_column_and_its_trigger_are_gone():
    """Nothing reads them after ADR-0013. A leftover trigger would fail every
    chunk insert once the column is dropped."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'kb_chunks' AND column_name = 'tsv'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_kb_chunks_tsv'")
        assert cursor.fetchone()[0] == 0
