"""
Checks the tables ai-engine declares and where its code writes.
"""

from __future__ import annotations

import re
from pathlib import Path

import ai_engine
from ai_engine.core.db.tables import Base

_GRANTED_TABLES = {"kb_articles", "kb_chunks", "fewshot_examples", "kb_article_associations"}

_WRITE_CALL = re.compile(
    r"\b(create_all|drop_all)\s*\(|\bsession\.(add|add_all|delete|merge|flush|commit)\s*\("
)
_WRITERS = {Path("core/db/client.py"), Path("core/associations/build.py")}
_WRITE_STATEMENT = re.compile(r"\bdb\.write\s*\(|\b(insert|update|delete)\s*\(\s*[A-Z]")

_SRC = Path(ai_engine.__file__).parent


def test_only_granted_tables_are_declared():
    """A business table declared here would fail only on the first ticket
    that queried it, as a permission error the policy lookup swallows into
    deny-by-default.
    """

    assert set(Base.metadata.tables) == _GRANTED_TABLES


def _code(path: Path) -> str:
    """Strips docstrings and comments from a file's code."""

    return re.sub(r'"""[\s\S]*?"""|#.*', "", path.read_text(encoding="utf-8"))


def test_no_orm_write_or_ddl_calls_in_ai_engine():
    offenders = []
    for path in _SRC.rglob("*.py"):
        for match in _WRITE_CALL.finditer(_code(path)):
            offenders.append(f"{path.relative_to(_SRC)}: {match.group(0)}")

    assert offenders == []


def test_only_the_offline_build_writes():
    offenders = []
    for path in _SRC.rglob("*.py"):
        if path.relative_to(_SRC) in _WRITERS:
            continue
        for match in _WRITE_STATEMENT.finditer(_code(path)):
            offenders.append(f"{path.relative_to(_SRC)}: {match.group(0)}")

    assert offenders == []
