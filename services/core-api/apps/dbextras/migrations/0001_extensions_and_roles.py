"""
Runs FIRST, before any app that has a vector column (tickets, kb,
fewshot) — CREATE EXTENSION vector must exist before those columns can be
created. Executes infra/migrations/sql/0001_extensions_and_roles.sql
verbatim, then a RunPython step gives ai_engine_ro a real password (kept
out of the committed .sql file — see that file's header comment) and
creates the two public-ID sequences used by apps/tickets/services/ids.py.

`manage.py migrate` stays the single entry point (spec §2 rule 1
extended to infra), which is why this reads the checked-in .sql file
rather than duplicating its contents inline.
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


def set_ai_engine_ro_password(apps, schema_editor):
    password = settings.AI_ENGINE_RO_PASSWORD
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER ROLE ai_engine_ro WITH LOGIN PASSWORD %s", [password])


def unset_ai_engine_ro_password(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER ROLE ai_engine_ro WITH NOLOGIN")


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql=_read("0001_extensions_and_roles.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(set_ai_engine_ro_password, unset_ai_engine_ro_password),
        migrations.RunSQL(
            sql=(
                "CREATE SEQUENCE IF NOT EXISTS ticket_public_id_seq;"
                "CREATE SEQUENCE IF NOT EXISTS incident_public_id_seq;"
            ),
            reverse_sql=(
                "DROP SEQUENCE IF EXISTS ticket_public_id_seq;"
                "DROP SEQUENCE IF EXISTS incident_public_id_seq;"
            ),
        ),
    ]
