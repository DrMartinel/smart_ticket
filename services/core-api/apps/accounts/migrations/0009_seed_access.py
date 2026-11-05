"""Seeds the default department and system roles, and moves capabilities and team
leads into grants (F14 §i phase 2)."""

from django.db import migrations

SYSTEM_ROLES = {
    "employee": "Employee",
    "technician": "Technician",
    "manager": "Manager",
    "security": "Security",
    "workflow-admin": "Workflow admin",
    "kb-editor": "Knowledge editor",
    "incident-manager": "Incident manager",
    "team-lead": "Team lead",
    "department-head": "Department head",
}
CAPABILITY_ROLES = {
    "workflow_admin": "workflow-admin",
    "kb_editor": "kb-editor",
    "incident_manager": "incident-manager",
}
URN = "urn:smart-ticket:role:system:{}"


def forward(apps, schema_editor):
    Department = apps.get_model("accounts", "Department")
    Role = apps.get_model("accounts", "Role")
    Assignment = apps.get_model("accounts", "Assignment")
    User = apps.get_model("accounts", "User")
    UserCapability = apps.get_model("accounts", "UserCapability")
    TeamMembership = apps.get_model("teams", "TeamMembership")

    default, _ = Department.objects.get_or_create(
        is_default=True, defaults={"code": "GENERAL", "name": "General"}
    )
    User.objects.filter(department__isnull=True).update(department=default)
    roles = {
        key: Role.objects.get_or_create(
            urn=URN.format(key), defaults={"name": name, "is_system": True}
        )[0]
        for key, name in SYSTEM_ROLES.items()
    }
    for row in UserCapability.objects.all():
        Assignment.objects.create(
            user_id=row.user_id,
            role=roles[CAPABILITY_ROLES[row.capability]],
            source="migrated",
            reason="capability before F14",
            starts_at=row.granted_at,
        )
    for membership in TeamMembership.objects.filter(role="lead"):
        Assignment.objects.create(
            user_id=membership.user_id,
            role=roles["team-lead"],
            scope_kind="team",
            scope_team_id=membership.team_id,
            source="structural",
            reason="team lead",
        )


def backward(apps, schema_editor):
    Assignment = apps.get_model("accounts", "Assignment")
    UserCapability = apps.get_model("accounts", "UserCapability")
    by_role = {URN.format(v): k for k, v in CAPABILITY_ROLES.items()}
    for row in Assignment.objects.filter(ended_at__isnull=True, scope_kind="global").select_related(
        "role"
    ):
        if row.role.urn in by_role:
            UserCapability.objects.get_or_create(
                user_id=row.user_id, capability=by_role[row.role.urn]
            )
    Assignment.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_org_and_access"),
        ("teams", "0005_drop_keycloak_groups"),
    ]

    operations = [migrations.RunPython(forward, backward)]
