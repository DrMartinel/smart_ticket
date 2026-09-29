from django.apps import AppConfig


class DbExtrasConfig(AppConfig):
    """Database plumbing that belongs to no business app. No models of its
    own. Hosts the two cross-cutting SQL migrations that (a) must run BEFORE
    any app with a vector column (extensions/roles) and (b) must run AFTER
    every business app's tables exist (indexes/constraints/triggers/grants) —
    see migrations/ for why this needed its own app rather than living inside
    e.g. `tickets`. (`wait_for_db` knows no domain, so it lives in
    `apps.core`.)"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dbextras"
    label = "dbextras"
