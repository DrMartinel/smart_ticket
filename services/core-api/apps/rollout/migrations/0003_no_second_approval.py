"""Closes what was waiting for a second person (ADR-0043): flag requests expire and their flags
go back off, gate changes expire, submitted threshold changes go back to draft."""

from django.db import migrations, models
from django.utils import timezone


def close_pending(apps, schema_editor):
    now = timezone.now()
    apps.get_model("rollout", "FlagRequest").objects.filter(state="pending").update(
        state="expired", decided_at=now, decided_reason="second approvals were removed"
    )
    apps.get_model("rollout", "RolloutFlag").objects.filter(state="pending_on").update(state="off")
    apps.get_model("rollout", "GateChange").objects.filter(state="pending").update(
        state="expired", decided_at=now
    )
    apps.get_model("rollout", "ThresholdChangeRequest").objects.filter(state="pending").update(
        state="draft", approvals=[]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("rollout", "0002_seed"),
    ]

    operations = [
        migrations.RunPython(close_pending, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rolloutflag",
            name="state",
            field=models.CharField(
                choices=[("off", "off"), ("on", "on")], default="off", max_length=12
            ),
        ),
        migrations.AlterField(
            model_name="thresholdchangerequest",
            name="state",
            field=models.CharField(
                choices=[
                    ("draft", "draft"),
                    ("approved", "approved"),
                    ("rejected", "rejected"),
                    ("loaded", "loaded"),
                ],
                default="draft",
                max_length=10,
            ),
        ),
    ]
