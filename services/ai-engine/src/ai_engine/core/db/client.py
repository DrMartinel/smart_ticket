"""
The database client: the only place ai-engine opens a DB session.

Nodes must NOT construct `SqlAlchemySessionSource` themselves.
`build_providers()` (core/providers/factory.py) builds the single instance at
startup and nodes receive it as `db`. To query, take a session from it and
`execute` a statement built against `tables.py`.

Read-only access. Connects as `ai_engine_ro`, which — per
infra/migrations/sql/0004_grants_and_audit_lockdown.sql — has SELECT-only
grants on exactly three tables: kb_articles, kb_chunks, fewshot_examples.
Any query against a business table (tickets, ai_runs, routing_decisions,
audit_log, ...) fails at the database layer, not just by convention
(ADR-0004). This module should never be extended to query anything else.

Queries are built with SQLAlchemy 2.0 against `core/db/tables.py` (ADR-0008);
psycopg 3 is still the driver underneath.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ai_engine.core.config import settings


def _psycopg3_url(url: str) -> str:
    """SQLAlchemy maps a bare `postgresql://` to psycopg2, which is not
    installed, so `create_engine` would raise ModuleNotFoundError at boot.
    Forcing the driver here keeps DATABASE_URL in the plain form docker-compose,
    CI and the evals already use."""

    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


class SqlAlchemySessionSource:
    """Opens a fresh read-only session per use.

    NullPool, not SQLAlchemy's default QueuePool: every `connect()` opens and
    closes a real connection, exactly as the plain-psycopg version did — see
    the module docstring on the `ai_engine_ro` grant model.

    Construction opens NO socket (`create_engine` is lazy), which is what lets
    main.py build the graph at uvicorn import time. Safe to share across
    FastAPI's threadpool: the engine is thread-safe and each use gets its own
    Session.
    """

    def __init__(self) -> None:
        self._engine = create_engine(_psycopg3_url(settings.database_url), poolclass=NullPool)

    @contextmanager
    def connect(self):
        # Never committed: the session's implicit transaction is rolled back on
        # close. ai-engine has nothing to commit (ADR-0004).
        with Session(self._engine) as session:
            yield session
