"""Adds the workflow rules that choose a ticket's workflow at handoff (ADR-0055)."""

import django.db.models.constraints
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0004_category_workflow"),
        ("lifecycle", "0007_drop_approvals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowRule",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("order", models.PositiveIntegerField()),
                ("branch", models.CharField(blank=True, max_length=20, null=True)),
                (
                    "priority",
                    models.CharField(
                        blank=True,
                        choices=[("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P4", "P4")],
                        max_length=2,
                        null=True,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("change_reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        db_column="category",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workflow_rules",
                        to="categories.category",
                        to_field="slug",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rules",
                        to="lifecycle.workflow",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_rules",
                "ordering": ["order"],
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        deferrable=django.db.models.constraints.Deferrable["DEFERRED"],
                        fields=("order",),
                        name="uq_workflow_rule_order",
                    )
                ],
            },
        ),
    ]
