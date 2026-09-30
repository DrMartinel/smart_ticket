"""
Moves lexical retrieval from `kb_chunks.tsv` to a pg_search BM25 index
(ADR-0013) by running infra/migrations/sql/0005_pg_search_bm25.sql. It drops
the `tsv` trigger first, so `kb.0002` can then remove the column without
leaving a trigger that writes to a column that no longer exists.
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


class Migration(migrations.Migration):
    dependencies = [("dbextras", "0002_finalize")]

    operations = [
        migrations.RunSQL(sql=_read("0005_pg_search_bm25.sql"), reverse_sql=migrations.RunSQL.noop),
    ]
