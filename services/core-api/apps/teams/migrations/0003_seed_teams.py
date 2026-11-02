"""One team per category, `least_loaded`, with `other` as the fallback (F2 §g); keeps teams
F13 already made from Keycloak groups, and fills `tickets.team` from `assigned_team`."""

from django.db import migrations

# slug, name, as F2 §g shipped them.
TEAMS = [
    ("hardware", "Hardware"),
    ("software", "Software"),
    ("network", "Network"),
    ("access", "Access"),
    ("security", "Security"),
    ("other", "Service desk"),
]
FALLBACK = "other"


def seed(apps, schema_editor):
    Team = apps.get_model("teams", "Team")
    TeamCategory = apps.get_model("teams", "TeamCategory")
    Ticket = apps.get_model("tickets", "Ticket")
    has_fallback = Team.objects.filter(is_fallback=True).exists()
    for slug, name in TEAMS:
        team, _ = Team.objects.get_or_create(
            slug=slug, defaults={"name": name, "strategy": "least_loaded"}
        )
        if slug == FALLBACK and not has_fallback:
            team.is_fallback = True
            team.save(update_fields=["is_fallback"])
        if not TeamCategory.objects.filter(category=slug).exists():
            TeamCategory.objects.create(team=team, category=slug)
    for team in Team.objects.all():
        Ticket.objects.filter(assigned_team=team.slug, team__isnull=True).update(team=team)


def unseed(apps, schema_editor):
    apps.get_model("tickets", "Ticket").objects.update(team=None)
    apps.get_model("teams", "TeamCategory").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0002_categories_leaves_reassignments"),
        ("tickets", "0006_ticket_team"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
