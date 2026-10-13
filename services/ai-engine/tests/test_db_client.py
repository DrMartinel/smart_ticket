"""
The DB client's connection pool. Every read borrows its own connection, about
ten per ticket; without a pool each one is a new Postgres connection (TCP,
auth, backend start). With a pool that dies silently, a dropped connection
is handed to a node and the ticket fails as `ai_engine_unavailable`.

Also the client's `write`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import QueuePool, StaticPool

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


def _sqlite_source(monkeypatch):
    """Builds a client on an in-memory SQLite database."""

    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE t (x INTEGER PRIMARY KEY)"))
    source = SqlAlchemySessionSource()
    monkeypatch.setattr(source, "_engine", engine)
    return source


def test_a_failed_write_step_rolls_back_the_steps_before_it(monkeypatch):
    source = _sqlite_source(monkeypatch)
    source.write([(text("INSERT INTO t (x) VALUES (:x)"), [{"x": 1}])])

    with pytest.raises(IntegrityError):
        source.write(
            [
                (text("DELETE FROM t"), None),
                (text("INSERT INTO t (x) VALUES (:x)"), [{"x": 2}, {"x": 2}]),
            ]
        )

    assert [tuple(r) for r in source.all(text("SELECT x FROM t"))] == [(1,)]


def test_a_write_with_no_rows_runs_the_other_steps(monkeypatch):
    source = _sqlite_source(monkeypatch)
    source.write([(text("INSERT INTO t (x) VALUES (:x)"), [{"x": 1}])])

    source.write([(text("DELETE FROM t"), None), (text("INSERT INTO t (x) VALUES (:x)"), [])])

    assert source.all(text("SELECT x FROM t")) == []
