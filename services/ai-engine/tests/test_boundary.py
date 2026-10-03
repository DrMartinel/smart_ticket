"""
ai-engine's layering: main.py → graph/ → schemas.py, and both → core/.
`core` is infrastructure (settings, prompts, DB, model clients) and must not
reach up into the pipeline or the HTTP layer; `schemas` is the wire contract
mirrored in core-api (ADR-0010) and depends on nothing in ai-engine. An
upward import is how a "foundation" quietly starts depending on the graph,
and then can't be reused or tested without it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ai_engine

_SRC = Path(ai_engine.__file__).parent

# Package (or module) -> the ai_engine modules it must never import.
_FORBIDDEN = {
    "core": ("ai_engine.graph", "ai_engine.schemas", "ai_engine.main"),
    "schemas.py": ("ai_engine.",),
    "graph": ("ai_engine.main",),
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _files(part: str) -> list[Path]:
    target = _SRC / part
    return [target] if target.is_file() else sorted(target.rglob("*.py"))


@pytest.mark.parametrize("part", _FORBIDDEN, ids=list(_FORBIDDEN))
def test_no_upward_imports(part):
    bad = [
        f"{path.relative_to(_SRC)} imports {module}"
        for path in _files(part)
        for module in _imports(path)
        if module.startswith(_FORBIDDEN[part])
    ]
    assert bad == []
