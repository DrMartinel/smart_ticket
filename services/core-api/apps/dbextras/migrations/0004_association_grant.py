"""
Grants ai-engine's read-only role SELECT on `kb_article_associations`
(ADR-0018) by running infra/migrations/sql/0006_association_grant.sql. Runs
after the table exists (`kb.0004`), like 0002_finalize runs the original
grants after every business table.
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


class Migration(migrations.Migration):
    dependencies = [("dbextras", "0003_pg_search_bm25"), ("kb", "0004_associations")]

    operations = [
        migrations.RunSQL(
            sql=_read("0006_association_grant.sql"),
            reverse_sql="REVOKE SELECT ON kb_article_associations FROM ai_engine_ro;",
        ),
    ]
