"""Adds what a PII reveal records (F5): the ticket, the placeholder, the
reason code, the claimed review item and the outcome. The table holds no
rows yet, so the required columns are added nullable and then made NOT NULL."""

import django.db.models.deletion
from django.db import migrations, models

REASONS = [
    ("verify_identity", "verify_identity"),
    ("contact_requester", "contact_requester"),
    ("security_investigation", "security_investigation"),
    ("legal_request", "legal_request"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("review", "0002_alter_reviewitem_queue"),
        ("tickets", "0004_ticket_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="piiaccesslog",
            name="ticket",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pii_reveals",
                to="tickets.ticket",
            ),
        ),
        migrations.AddField(
            model_name="piiaccesslog",
            name="placeholder",
            field=models.CharField(max_length=40, null=True),
        ),
        migrations.AddField(
            model_name="piiaccesslog",
            name="reason_code",
            field=models.CharField(choices=REASONS, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="piiaccesslog",
            name="review_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="review.reviewitem",
            ),
        ),
        migrations.AddField(
            model_name="piiaccesslog",
            name="outcome",
            field=models.CharField(default="revealed", max_length=20),
        ),
        migrations.AlterField(
            model_name="piiaccesslog",
            name="ticket",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pii_reveals",
                to="tickets.ticket",
            ),
        ),
        migrations.AlterField(
            model_name="piiaccesslog",
            name="placeholder",
            field=models.CharField(max_length=40),
        ),
        migrations.AlterField(
            model_name="piiaccesslog",
            name="reason_code",
            field=models.CharField(choices=REASONS, max_length=30),
        ),
    ]
