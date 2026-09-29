"""
`apps/core` is the shared foundation: every app may import from it, and it
imports from no app. The rule is "delete every domain app and `core` still
imports cleanly". These tests pin it, so a dependency pointing the wrong way
fails here, the moment it is added, instead of quietly turning `core` into
one more app every other app transitively depends on.
"""

import ast
import importlib
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[1]

# Top-level packages of core-api that are not `core`. `config` is allowed
# (settings are the environment, not an app), and so is Django.
_FORBIDDEN = ("apps.", "common", "infrastructure")


def _core_modules() -> list[Path]:
    return sorted(p for p in _CORE.rglob("*.py") if "tests" not in p.relative_to(_CORE).parts)


def _dotted(path: Path) -> str:
    parts = path.relative_to(_CORE.parents[1]).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _is_forbidden(name: str) -> bool:
    if name == "apps.core" or name.startswith("apps.core."):
        return False
    return any(name == f.rstrip(".") or name.startswith(f) for f in _FORBIDDEN)


@pytest.mark.parametrize("path", _core_modules(), ids=lambda p: str(p.relative_to(_CORE)))
def test_core_imports_no_app(path):
    """Includes imports inside functions and TYPE_CHECKING blocks: a
    deferred import is still a dependency."""

    wrong_way = sorted(n for n in _imported_names(path) if _is_forbidden(n))
    assert wrong_way == [], f"{path.name} imports {wrong_way}; move that code out of core"


@pytest.mark.parametrize("path", _core_modules(), ids=lambda p: str(p.relative_to(_CORE)))
def test_every_core_module_imports(path):
    importlib.import_module(_dotted(path))


def test_the_scan_sees_a_wrong_way_import():
    """Guards the guard: a scan that silently matched nothing would pass."""

    assert _is_forbidden("apps.tickets.models")
    assert _is_forbidden("infrastructure.dtos")
    assert _is_forbidden("common.permissions")
    assert not _is_forbidden("apps.core.models")
    assert not _is_forbidden("django.db")
    assert len(_core_modules()) >= 5
