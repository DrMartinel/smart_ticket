"""
The only place ai-engine opens a DB session. `build_providers()` builds the
single instance; nodes receive it as `db` and never construct their own.

Connects as `ai_engine_ro`, SELECT-only on kb_articles, kb_chunks and
fewshot_examples (0004_grants_and_audit_lockdown.sql). A query against any
business table fails at the database (ADR-0004) — never extend this beyond
those three. Queries are SQLAlchemy 2.0 against `tables.py` (ADR-0008).
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ai_engine.core.config import settings


def _psycopg3_url(url: str) -> str:
    """A bare `postgresql://` makes SQLAlchemy pick psycopg2, which is not
    installed. Forcing psycopg 3 keeps DATABASE_URL in its plain form.
    """

    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


class SqlAlchemySessionSource:
    """Opens a fresh read-only session per use (NullPool: one real connection
    per `connect()`).

    Construction opens no socket, so main.py can build the graph at import
    time. Thread-safe: each use gets its own Session.
    """

    def __init__(self) -> None:
        self._engine = create_engine(_psycopg3_url(settings.database_url), poolclass=NullPool)

    @contextmanager
    def connect(self):
        # Never committed: the session's implicit transaction is rolled back on
        # close. ai-engine has nothing to commit (ADR-0004).
        with Session(self._engine) as session:
            yield session
