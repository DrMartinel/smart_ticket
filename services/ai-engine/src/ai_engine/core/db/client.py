"""
The only place ai-engine opens a DB session. `db`, at the bottom, is the
single instance; query code runs each read through `db.all` or `db.first`
and never opens a session itself.

Connects as `ai_engine_ro`, SELECT-only on kb_articles, kb_chunks and
fewshot_examples (0004_grants_and_audit_lockdown.sql). A query against any
business table fails at the database (ADR-0004) — never extend this beyond
those three. Queries are SQLAlchemy 2.0 against `tables.py` (ADR-0008).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Executable, Row, create_engine, make_url
from sqlalchemy.orm import Session

from ai_engine.core.config import settings


def _psycopg3_url(url: str) -> str:
    """A bare `postgresql://` makes SQLAlchemy pick psycopg2, which is not
    installed. Forcing psycopg 3 keeps DATABASE_URL in its plain form.
    """

    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


class SqlAlchemySessionSource:
    """Runs each read on a connection borrowed from a pool for that read
    only, and hands it straight back.

    One borrow per read, never one session for the app or for a node:
    FastAPI runs tickets on a threadpool and a Session is not thread-safe,
    and a session held across a model call would sit idle in transaction for
    minutes. With a pool a borrow costs no round trip to open a connection.
    `pool_pre_ping` swaps out a connection Postgres has dropped (a restart, a
    network blip) instead of handing it to a read.

    Construction opens no socket, so main.py can build the graph at import
    time: connections open on first use.
    """

    def __init__(self) -> None:
        self._engine = create_engine(
            _psycopg3_url(settings.database_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
        )

    # Never committed: each session's implicit transaction is rolled back on
    # close. ai-engine has nothing to commit (ADR-0004).

    def all(self, statement: Executable) -> Sequence[Row[Any]]:
        with Session(self._engine) as session:
            return session.execute(statement).all()

    def first(self, statement: Executable) -> Row[Any] | None:
        with Session(self._engine) as session:
            return session.execute(statement).first()


db = SqlAlchemySessionSource()
