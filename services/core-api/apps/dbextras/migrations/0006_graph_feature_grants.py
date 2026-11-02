"""
Grants ai-engine's role what the entity-graph feature needs by running
infra/migrations/sql/0009_graph_feature_grants.sql (ADR-0037).
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


class Migration(migrations.Migration):
    dependencies = [
        ("dbextras", "0005_audit_log_actor_index"),
        ("dbextras", "0005_pii_access_log_lockdown"),
        ("kb", "0007_graph_feature"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_read("0009_graph_feature_grants.sql"),
            reverse_sql=(
                "REVOKE SELECT ON kb_association_overrides FROM ai_engine_ro; "
                "REVOKE SELECT, UPDATE ON kb_graph_rebuild_requests FROM ai_engine_ro;"
            ),
        ),
    ]
