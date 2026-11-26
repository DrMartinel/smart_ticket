"""Each pick names the turn its press sent; a pick recorded before gets the conversation's last
turn queued by the time it was pressed."""

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def turn_of_each_pick(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Gives each pick the last turn of its conversation queued by the time it was pressed, and
    deletes a pick no turn came before."""
    ResourcePick = apps.get_model("infra", "ResourcePick")
    AgentTurn = apps.get_model("agent", "AgentTurn")
    for pick in ResourcePick.objects.all():
        turn = (
            AgentTurn.objects.filter(
                conversation_id=pick.conversation_id, queued_at__lte=pick.picked_at
            )
            .order_by("-seq")
            .first()
        )
        if turn is None:
            pick.delete()
        else:
            ResourcePick.objects.filter(pk=pick.pk).update(turn=turn)


class Migration(migrations.Migration):
    dependencies = [
        ("agent", "0005_turn_read_calls"),
        ("infra", "0006_resource_picks"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="resourcepick", name="uq_resource_pick"),
        migrations.AddField(
            model_name="resourcepick",
            name="turn",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="agent.agentturn",
            ),
        ),
        migrations.RunPython(turn_of_each_pick, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="resourcepick",
            name="turn",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="agent.agentturn",
            ),
        ),
        migrations.AddConstraint(
            model_name="resourcepick",
            constraint=models.UniqueConstraint(
                fields=("turn", "resource_id"), name="uq_resource_pick"
            ),
        ),
    ]
