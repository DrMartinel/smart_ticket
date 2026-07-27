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


@contextmanager
def get_connection():
    conn = psycopg.connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()
