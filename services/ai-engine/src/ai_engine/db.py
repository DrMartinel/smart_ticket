"""
Read-only DB access. Connects as `ai_engine_ro`, which — per
infra/migrations/sql/0004_grants_and_audit_lockdown.sql — has SELECT-only
grants on exactly three tables: kb_articles, kb_chunks, fewshot_examples.
Any query against a business table (tickets, ai_runs, routing_decisions,
audit_log, ...) fails at the database layer, not just by convention
(ADR-0004). This module should never be extended to query anything else.
"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg

from ai_engine.config import settings


class PsycopgConnectionSource:
    """Opens a fresh read-only connection per use. No pool — see the module
    docstring on the `ai_engine_ro` grant model.

    Construction opens NO socket, which is what lets main.py build the graph at
    uvicorn import time and in a test with no database at all. Stateless, so
    one instance is safe to share across FastAPI's threadpool.
    """

    @contextmanager
    def connect(self):
        conn = psycopg.connect(settings.database_url)
        try:
            yield conn
        finally:
            conn.close()
