from django.apps import AppConfig


class DbExtrasConfig(AppConfig):
    """No models of its own. Exists purely to host the two cross-cutting
    SQL migrations that (a) must run BEFORE any app with a vector column
    (extensions/roles) and (b) must run AFTER every business app's tables
    exist (indexes/constraints/triggers/grants) — see migrations/ for why
    this needed its own app rather than living inside e.g. `tickets`."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dbextras"
    label = "dbextras"
