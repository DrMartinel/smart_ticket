"""
Abstract base models. No tables: a concrete model belongs to its own app.
"""

import uuid

from django.db import models


class BaseModel(models.Model):
    """A UUID (v4) primary key instead of Django's bigint default (ADR-0011):
    sequential ids leak volume and are guessable. Every business model
    inherits it; `test_every_model_has_a_uuid_primary_key` fails for one that
    falls back to `DEFAULT_AUTO_FIELD`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True
