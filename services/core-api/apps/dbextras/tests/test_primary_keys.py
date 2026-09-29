"""
Every business table is keyed by a UUID (ADR-0011).

`DEFAULT_AUTO_FIELD` is still `BigAutoField`, because Django's own
auto-created tables (the user-to-group link table) need an integer key. So a
new model that forgets `id = models.UUIDField(primary_key=True, ...)` does not
fail anywhere: it quietly gets a bigint key, and its id then breaks every
place that expects a UUID (API schemas, the ai-engine wire, Celery task
arguments). This test is the only thing that notices.
"""

from django.apps import apps
from django.db import models

OUR_APPS = {"accounts", "audit", "tickets", "kb", "review", "fewshot", "itsm_mock", "metrics"}


def test_every_model_has_a_uuid_primary_key():
    wrong: list[str] = []
    for model in apps.get_models():
        if model._meta.app_label not in OUR_APPS:
            continue
        pk = model._meta.pk
        assert pk is not None
        # A one-to-one primary key (TicketEmbedding -> Ticket) takes the
        # column type of the row it points at.
        target = pk.target_field if isinstance(pk, models.OneToOneField) else pk
        if not isinstance(target, models.UUIDField):
            wrong.append(f"{model._meta.label}.{pk.name} is {type(target).__name__}")
    assert wrong == []
