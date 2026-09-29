from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Installed so Django finds `management/commands/`. Abstract models
    only, so it has no migrations and creates no tables."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
