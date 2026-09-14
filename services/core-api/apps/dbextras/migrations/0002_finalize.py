"""
Runs LAST — depends on every business app's initial migration, because it
adds indexes, constraints, triggers, and grants that reference tables
across all of them (tickets, kb_chunks, fewshot_examples, review_items,
audit_log, ...). This is exactly the case the plan called out: "what
Django's ORM can't express" (partial HNSW, CHECK constraints tied to
business rules, a BEFORE INSERT trigger, and role-based GRANT/REVOKE).
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
        cursor.execute(f'REVOKE UPDATE, DELETE ON audit_log FROM "{role}"')


def grant_back_to_app_role(apps, schema_editor):
    role = settings.DB_APP_ROLE
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'GRANT UPDATE, DELETE ON audit_log TO "{role}"')


class Migration(migrations.Migration):
    dependencies = [
        ("dbextras", "0001_extensions_and_roles"),
        ("accounts", "0001_initial"),
        ("audit", "0001_initial"),
        ("tickets", "0001_initial"),
        ("kb", "0001_initial"),
        ("review", "0001_initial"),
        ("fewshot", "0001_initial"),
        ("itsm_mock", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=_read("0002_indexes.sql"), reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(
            sql=_read("0003_constraints_and_triggers.sql"), reverse_sql=migrations.RunSQL.noop
        ),
        migrations.RunSQL(
            sql=_read("0004_grants_and_audit_lockdown.sql"), reverse_sql=migrations.RunSQL.noop
        ),
        # Revoking UPDATE/DELETE from the specific app role core-api itself
        # connects as (spec: audit_log is append-only, no exceptions) — see
        # infra/migrations/sql/0004_grants_and_audit_lockdown.sql's header
        # for why this part isn't in the static file.
        migrations.RunPython(revoke_from_app_role, grant_back_to_app_role),
    ]
