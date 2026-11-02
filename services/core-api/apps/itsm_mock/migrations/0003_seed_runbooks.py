"""Seeds the F12 §g runbooks, unapproved until a manager approves each, and backfills pre-F12
executions: `state` from `status`, the catalog row, the payload that ran and an idempotency key."""

from django.db import migrations

SEED = [
    {
        "code": "RB-RESET-PASSWORD",
        "title": "Reset user password",
        "executor": "keycloak",
        "config": {"action": "send_password_reset"},
        "required_fields": ["target_username"],
        "target_rule": "reporter",
        "risk": "low",
    },
    {
        "code": "RB-UNLOCK-ACCOUNT",
        "title": "Unlock user account",
        "executor": "keycloak",
        "config": {"action": "unlock_account"},
        "required_fields": ["target_username"],
        "target_rule": "reporter",
        "risk": "low",
    },
    {
        "code": "RB-GRANT-ACCESS",
        "title": "Grant application access",
        "executor": "keycloak",
        "config": {
            "action": "add_to_group",
            "allowed_groups": ["/apps/jira-users", "/apps/vpn-users"],
        },
        "required_fields": ["target_username", "group"],
        "target_rule": "any",
        "risk": "high",
    },
    {
        "code": "RB-RESTART-SERVICE",
        "title": "Restart a service",
        "executor": "n8n",
        "config": {"url": "https://n8n.congty.vn/webhook/restart-service"},
        "required_fields": ["service_name", "host"],
        "target_rule": "any",
        "risk": "high",
    },
]


def seed(apps, schema_editor):
    Runbook = apps.get_model("itsm_mock", "Runbook")
    RunbookExecution = apps.get_model("itsm_mock", "RunbookExecution")
    for row in SEED:
        Runbook.objects.get_or_create(code=row["code"], defaults=row)
    by_code = {r.code: r for r in Runbook.objects.all()}
    attempts: dict = {}
    for execution in RunbookExecution.objects.order_by("executed_at"):
        n = attempts[execution.review_item_id] = attempts.get(execution.review_item_id, 0) + 1
        execution.state = execution.status or "succeeded"
        execution.runbook = by_code.get(execution.runbook_code)
        execution.executed_payload = execution.payload
        execution.executor = "mock"
        execution.attempt = n
        execution.idempotency_key = f"{execution.review_item_id}:{n}"
        execution.finished_at = execution.executed_at
        execution.save()


class Migration(migrations.Migration):
    dependencies = [("itsm_mock", "0002_runbook_catalog")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
