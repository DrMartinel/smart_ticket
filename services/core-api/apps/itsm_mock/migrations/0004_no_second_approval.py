"""Fails the executions still waiting for a second manager (ADR-0043); a person executes them
again."""

from django.db import migrations, models
from django.utils import timezone


def fail_waiting(apps, schema_editor):
    RunbookExecution = apps.get_model("itsm_mock", "RunbookExecution")
    RunbookExecution.objects.filter(state="awaiting_second_approval").update(
        state="failed",
        error="second approvals were removed (ADR-0043); execute it again",
        finished_at=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("itsm_mock", "0003_seed_runbooks"),
    ]

    operations = [
        migrations.RunPython(fail_waiting, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="runbookexecution",
            name="state",
            field=models.CharField(
                choices=[
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
    ]
