"""The runbook catalog and the execution fields F12 records (ADR-0038)."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("itsm_mock", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="runbookexecution",
            options={"ordering": ["-executed_at"]},
        ),
        migrations.AlterField(
            model_name="runbookexecution",
            name="runbook_id",
            field=models.CharField(db_column="runbook_id", max_length=64),
        ),
        migrations.RenameField(
            model_name="runbookexecution",
            old_name="runbook_id",
            new_name="runbook_code",
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="attempt",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="awaiting_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="executed_payload",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="executor",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="external_ref",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="idempotency_key",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="resolution_note",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="resolved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="second_approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="second_approver",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="state",
            field=models.CharField(
                choices=[
                    ("awaiting_second_approval", "awaiting_second_approval"),
                    ("queued", "queued"),
                    ("running", "running"),
                    ("succeeded", "succeeded"),
                    ("failed", "failed"),
                    ("unknown", "unknown"),
                ],
                default="queued",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="runbookexecution",
            name="status",
            field=models.CharField(blank=True, default=None, max_length=20, null=True),
        ),
        migrations.CreateModel(
            name="Runbook",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("code", models.CharField(max_length=64, unique=True)),
                ("title", models.CharField(max_length=200)),
                (
                    "executor",
                    models.CharField(
                        choices=[("keycloak", "keycloak"), ("n8n", "n8n"), ("mock", "mock")],
                        max_length=10,
                    ),
                ),
                ("config", models.JSONField(default=dict)),
                ("required_fields", models.JSONField(default=list)),
                (
                    "target_rule",
                    models.CharField(
                        choices=[("reporter", "reporter"), ("any", "any")], max_length=10
                    ),
                ),
                (
                    "risk",
                    models.CharField(choices=[("low", "low"), ("high", "high")], max_length=10),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("pending_change", models.JSONField(blank=True, null=True)),
                ("drafted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "drafted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "itsm_runbooks",
                "ordering": ["code"],
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="runbookexecution",
            name="runbook",
            field=models.ForeignKey(
                blank=True,
                db_column="itsm_runbook_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="executions",
                to="itsm_mock.runbook",
            ),
        ),
    ]
