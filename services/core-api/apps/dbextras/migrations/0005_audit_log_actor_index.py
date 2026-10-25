"""
Indexes `audit_log` by actor, event and time by running
infra/migrations/sql/0008_audit_log_actor_index.sql.
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


class Migration(migrations.Migration):
    dependencies = [("dbextras", "0004_association_grant")]

    operations = [
        migrations.RunSQL(
            sql=_read("0008_audit_log_actor_index.sql"),
            reverse_sql="DROP INDEX IF EXISTS idx_audit_actor_event;",
        ),
    ]
