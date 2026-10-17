"""Phase 2 builds only on accepted ADRs (PRE-2)."""

from __future__ import annotations

import re

import pytest

from config.settings import base

_ADR_DIR = base.REPO_ROOT / "docs" / "adr"
_STATUS = re.compile(r"^\*\*Status:\*\*\s*(.+)$", re.M)

# ADRs the phase 2 features sit on (docs/requirements/phase-2/06-PRE-prerequisites.md).
PHASE_2_FOUNDATIONS = ("0028", "0029")


def _status(number: str) -> str:
    (path,) = _ADR_DIR.glob(f"{number}-*.md")
    match = _STATUS.search(path.read_text())
    assert match, f"{path.name} has no **Status:** line"
    return match.group(1)


@pytest.mark.parametrize("number", PHASE_2_FOUNDATIONS)
def test_phase_2_does_not_build_on_an_unaccepted_adr(number: str) -> None:
    """AC-PRE2-01: each ADR phase 2 builds on says Accepted."""
    assert _status(number).startswith("Accepted"), f"ADR-{number} is {_status(number)!r}"
