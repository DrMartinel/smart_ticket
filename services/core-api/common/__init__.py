"""
Code shared by every app that belongs to none of them. Not a Django app — no
models, no migrations, nothing in INSTALLED_APPS.

Keep it to what several apps genuinely share. A helper used by one app lives
in that app.
"""
