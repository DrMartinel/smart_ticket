"""
Makes every category column reference ticket_categories by running
infra/migrations/sql/0010_category_foreign_keys.sql (ADR-0049).
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.BASE_DIR).parent.parent / "infra" / "migrations" / "sql"

REVERSE = [
    "ALTER TABLE tickets DROP CONSTRAINT IF EXISTS fk_tickets_category;",
    "ALTER TABLE incidents DROP CONSTRAINT IF EXISTS fk_incidents_category;",
    "ALTER TABLE kb_articles DROP CONSTRAINT IF EXISTS fk_kb_articles_category;",
    "ALTER TABLE kb_drafts DROP CONSTRAINT IF EXISTS fk_kb_drafts_category;",
    "ALTER TABLE sla_policies DROP CONSTRAINT IF EXISTS fk_sla_policies_category;",
    "ALTER TABLE fewshot_examples DROP CONSTRAINT IF EXISTS fk_fewshot_examples_category;",
    "ALTER TABLE team_categories DROP CONSTRAINT IF EXISTS fk_team_categories_category;",
    "ALTER TABLE review_decisions DROP CONSTRAINT IF EXISTS fk_review_decisions_corrected_category;",
    "ALTER TABLE team_reassignments DROP CONSTRAINT IF EXISTS fk_team_reassignments_from_category;",
    "ALTER TABLE team_reassignments DROP CONSTRAINT IF EXISTS fk_team_reassignments_to_category;",
    "ALTER TABLE report_ticket_facts DROP CONSTRAINT IF EXISTS fk_report_ticket_facts_category;",
]


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text()


class Migration(migrations.Migration):
    dependencies = [
        ("dbextras", "0006_graph_feature_grants"),
        ("categories", "0002_seed_categories"),
        ("tickets", "0014_agent_pii_critical"),
        ("kb", "0007_graph_feature"),
        ("sla", "0002_seed"),
        ("fewshot", "0001_initial"),
        ("teams", "0005_drop_keycloak_groups"),
        ("review", "0004_decided_via_and_agent_draft"),
        ("reports", "0002_ticketfacts_department"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_read("0010_category_foreign_keys.sql"),
            reverse_sql=" ".join(REVERSE),
        ),
    ]
