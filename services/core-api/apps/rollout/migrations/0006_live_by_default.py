"""Every flag on, each with a system audit row (ADR-0051)."""

from django.db import migrations, models
from django.utils import timezone

BRANCHES = ("auto_route", "auto_reply", "requester_questions", "agent_chat", "agent_console")
REASON = "ADR-0051: live by default"


def turn_on(apps, schema_editor):
    Flag = apps.get_model("rollout", "RolloutFlag")
    AuditLog = apps.get_model("audit", "AuditLog")
    for branch in BRANCHES:
        flag, _ = Flag.objects.get_or_create(branch=branch, defaults={"state": "off"})
        if flag.state == "on":
            continue
        flag.state = "on"
        flag.changed_by = None
        flag.changed_at = timezone.now()
        flag.reason = REASON
        flag.save(update_fields=["state", "changed_by", "changed_at", "reason"])
        AuditLog.objects.create(
            actor_type="system",
            event="rollout_flag_on",
            payload={"branch": branch, "reason": REASON},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("rollout", "0005_agent_flag_branches"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rolloutflag",
            name="state",
            field=models.CharField(
                choices=[("off", "off"), ("on", "on")], default="on", max_length=12
            ),
        ),
        migrations.RunPython(turn_on, migrations.RunPython.noop),
    ]
