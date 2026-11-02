"""
Checks `ai_engine_ro`'s F11 grants against the Dockerized Postgres (ADR-0037): it reads the
overrides and the rebuild requests, closes a request, and writes nothing else of either.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.backends.utils import CursorWrapper

from apps.accounts.models import User
from apps.kb.models import (
    KbArticle,
    KbAssociationOverride,
    KbGraphRebuildRequest,
    RebuildState,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def rows() -> KbGraphRebuildRequest:
    def article(slug: str) -> KbArticle:
        return KbArticle.objects.create(slug=slug, title=slug, body="x", category="network")

    editor = User.objects.create_user(username="mai.bn", password="x", role="technician")
    seed = article("client-vpn-user.windows-troubleshooting")
    KbAssociationOverride.objects.create(
        source_article=seed,
        target_article=article("workspaces-user.client_troubleshooting"),
        action="hide",
        reason="Không liên quan VPN",
        created_by=editor,
    )
    return KbGraphRebuildRequest.objects.create(article=seed, reason="publish")


@contextmanager
def _as_ai_engine() -> Iterator[CursorWrapper]:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE ai_engine_ro")
        try:
            yield cursor
        finally:
            cursor.execute("RESET ROLE")


def test_ai_engine_role_reads_overrides_and_requests(rows):
    with _as_ai_engine() as cursor:
        cursor.execute("SELECT action FROM kb_association_overrides")
        assert cursor.fetchall() == [("hide",)]
        cursor.execute("SELECT state FROM kb_graph_rebuild_requests")
        assert cursor.fetchall() == [("pending",)]


def test_ai_engine_role_closes_a_request(rows):
    with _as_ai_engine() as cursor:
        cursor.execute(
            "UPDATE kb_graph_rebuild_requests SET state = 'done', done_at = now(), build_id = 'b1'"
        )

    rows.refresh_from_db()
    assert (rows.state, rows.build_id) == (RebuildState.DONE.value, "b1")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO kb_association_overrides SELECT * FROM kb_association_overrides",
        "UPDATE kb_association_overrides SET action = 'add'",
        "DELETE FROM kb_association_overrides",
        "INSERT INTO kb_graph_rebuild_requests SELECT * FROM kb_graph_rebuild_requests",
        "UPDATE kb_graph_rebuild_requests SET reason = 'manual'",
        "UPDATE kb_graph_rebuild_requests SET article_id = article_id",
        "DELETE FROM kb_graph_rebuild_requests",
        "UPDATE kb_article_associations SET stale = false",
    ],
    ids=[
        "insert-overrides",
        "update-overrides",
        "delete-overrides",
        "insert-requests",
        "update-request-reason",
        "update-request-article",
        "delete-requests",
        "update-association-stale",
    ],
)
def test_ai_engine_role_writes_nothing_else_of_the_graph_feature(rows, sql):
    with _as_ai_engine() as cursor:
        with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
            cursor.execute(sql)
