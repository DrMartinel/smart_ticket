"""
The DB client's connection pool. Every read borrows its own connection, about
ten per ticket; without a pool each one is a new Postgres connection (TCP,
auth, backend start). With a pool that dies silently, a dropped connection
is handed to a node and the ticket fails as `ai_engine_unavailable`.
"""

from __future__ import annotations

from sqlalchemy.pool import QueuePool

from ai_engine.core.config import settings
from ai_engine.core.db.client import SqlAlchemySessionSource


def test_sessions_borrow_from_a_pool_sized_from_settings(monkeypatch):
    """A NullPool here would pass every unit test and quietly reconnect to
    Postgres on every read."""

    monkeypatch.setattr(settings, "db_pool_size", 3)
    monkeypatch.setattr(settings, "db_max_overflow", 2)

    pool = SqlAlchemySessionSource()._engine.pool

    assert isinstance(pool, QueuePool)
    assert (pool.size(), pool._max_overflow) == (3, 2)


def test_a_dropped_connection_is_replaced_not_handed_out():
    """Without pre-ping, the first ticket after a Postgres restart gets a
    dead connection from the pool and fails."""

    assert SqlAlchemySessionSource()._engine.pool._pre_ping is True


def test_building_the_client_opens_no_connection():
    """main.py builds the graph, and so this client, at import, with no
    database in unit tests."""

    assert SqlAlchemySessionSource()._engine.pool.checkedout() == 0
    assert SqlAlchemySessionSource()._engine.pool.checkedin() == 0
