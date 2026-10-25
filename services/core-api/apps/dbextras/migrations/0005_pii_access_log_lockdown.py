"""
Makes `pii_access_log` append-only by running
infra/migrations/sql/0007_pii_access_log_lockdown.sql, after the F5 columns
exist (`tickets.0005`).
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


def revoke_from_app_role(apps, schema_editor):
    role = settings.DB_APP_ROLE
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'REVOKE UPDATE, DELETE ON pii_access_log FROM "{role}"')


def grant_back_to_app_role(apps, schema_editor):
    role = settings.DB_APP_ROLE
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'GRANT UPDATE, DELETE ON pii_access_log TO "{role}"')


class Migration(migrations.Migration):
    dependencies = [
        ("dbextras", "0005_audit_log_actor_index"),
        ("tickets", "0005_pii_access_log_reveal"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_read("0007_pii_access_log_lockdown.sql"),
            reverse_sql=(
                "DROP TRIGGER IF EXISTS trg_pii_access_log_append_only ON pii_access_log;"
                "DROP FUNCTION IF EXISTS pii_access_log_deny_mutation();"
            ),
        ),
        migrations.RunPython(revoke_from_app_role, grant_back_to_app_role),
    ]
