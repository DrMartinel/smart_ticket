"""Pins every page allowed to auto-reply today to the text it has today (F6 §g): the live text is
the text that was approved, and for the demo KB it matches curation.json."""

import hashlib

from django.db import migrations


def backfill(apps, schema_editor):
    KbArticle = apps.get_model("kb", "KbArticle")
    for article in KbArticle.objects.filter(auto_reply_allowed=True, approved_text_sha256=None):
        text = f"{article.title}\n{article.body}"
        article.approved_text_sha256 = hashlib.sha256(text.encode()).hexdigest()
        article.save(update_fields=["approved_text_sha256"])


class Migration(migrations.Migration):
    dependencies = [("kb", "0005_governance")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
