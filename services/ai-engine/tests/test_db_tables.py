"""
The read-only boundary (ADR-0004) as seen from code. The `ai_engine_ro` role
is the real enforcement — these fail earlier, in CI, when someone starts
eroding it: declaring a business table, or writing through a session.
"""

from __future__ import annotations

import re
from pathlib import Path

import ai_engine
from ai_engine.core.db.tables import Base

# Exactly the SELECT grant in infra/migrations/sql/0004_grants_and_audit_lockdown.sql.
_GRANTED_TABLES = {"kb_articles", "kb_chunks", "fewshot_examples"}

_WRITE_CALL = re.compile(
    r"\b(create_all|drop_all)\s*\(|\bsession\.(add|add_all|delete|merge|flush|commit)\s*\("
)


def test_only_granted_tables_are_declared():
    """A business table (tickets, ai_runs, routing_decisions, ...) declared
    here would fail at the database anyway — but only on the first ticket
    that reached the query, as a permission error the policy lookup would
    swallow into deny-by-default."""

    assert set(Base.metadata.tables) == _GRANTED_TABLES


def test_no_write_or_ddl_calls_in_ai_engine():
    """ai-engine has no write authority. `tables.py` describes partial
    tables, so `create_all()` would also create wrong ones if the role ever
    allowed it. Docstrings and comments are stripped before matching."""

    src = Path(ai_engine.__file__).parent
    offenders = []
    for path in src.rglob("*.py"):
        code = re.sub(r'"""[\s\S]*?"""|#.*', "", path.read_text(encoding="utf-8"))
        for match in _WRITE_CALL.finditer(code):
            offenders.append(f"{path.relative_to(src)}: {match.group(0)}")

    assert offenders == []
