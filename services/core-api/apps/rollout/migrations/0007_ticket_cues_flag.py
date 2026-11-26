"""The ticket cues flag, on, with a system audit row (F17 §o.10, ADR-0051)."""

from django.db import migrations, models
from django.utils import timezone

REASON = "ADR-0051: live by default"


def seed(apps, schema_editor):
    Flag = apps.get_model("rollout", "RolloutFlag")
    AuditLog = apps.get_model("audit", "AuditLog")
    _, created = Flag.objects.get_or_create(
        branch="ticket_cues",
        defaults={"state": "on", "changed_at": timezone.now(), "reason": REASON},
    )
    if created:
        AuditLog.objects.create(
            actor_type="system",
            event="rollout_flag_on",
            payload={"branch": "ticket_cues", "reason": REASON},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("rollout", "0006_live_by_default"),
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
                    ("ticket_cues", "ticket_cues"),
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
                    ("ticket_cues", "ticket_cues"),
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
                    ("ticket_cues", "ticket_cues"),
                ],
                max_length=30,
            ),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
