"""The agent's two flags, off (F15, OQ-F15-06)."""

from django.db import migrations, models


def seed(apps, schema_editor):
    Flag = apps.get_model("rollout", "RolloutFlag")
    for branch in ("agent_chat", "agent_console"):
        Flag.objects.get_or_create(branch=branch)


class Migration(migrations.Migration):
    dependencies = [
        ("rollout", "0004_no_threshold_approval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="flagrequest",
            name="branch",
            field=models.CharField(
                choices=[
                    ("auto_route", "auto_route"),
                    ("auto_reply", "auto_reply"),
                    ("requester_questions", "requester_questions"),
                    ("agent_chat", "agent_chat"),
                    ("agent_console", "agent_console"),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="rolloutflag",
            name="branch",
            field=models.CharField(
                choices=[
                    ("auto_route", "auto_route"),
                    ("auto_reply", "auto_reply"),
                    ("requester_questions", "requester_questions"),
                    ("agent_chat", "agent_chat"),
                    ("agent_console", "agent_console"),
                ],
                max_length=30,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="rolloutgate",
            name="branch",
            field=models.CharField(
                choices=[
                    ("auto_route", "auto_route"),
                    ("auto_reply", "auto_reply"),
                    ("requester_questions", "requester_questions"),
                    ("agent_chat", "agent_chat"),
                    ("agent_console", "agent_console"),
                ],
                max_length=30,
            ),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
