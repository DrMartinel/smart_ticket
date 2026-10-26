"""Phase 2 builds only on accepted ADRs (PRE-2)."""

from __future__ import annotations

import re

import pytest

from config.settings import base

_ADR_DIR = base.REPO_ROOT / "docs" / "adr"
_STATUS = re.compile(r"^\*\*Status:\*\*[ \t]*(.+)$", re.M)

# ADRs the phase 2 features sit on (docs/requirements/phase-2/06-PRE-prerequisites.md).
PHASE_2_FOUNDATIONS = ("0028", "0029", "0030", "0031", "0032", "0033")


def _status(number: str) -> str:
    paths = sorted(_ADR_DIR.glob(f"{number}-*.md"))
    assert len(paths) == 1, f"expected one ADR-{number} in {_ADR_DIR}, found {paths}"
    match = _STATUS.search(paths[0].read_text())
    assert match, f"{paths[0].name} has no **Status:** line"
    return match.group(1)


@pytest.mark.parametrize("number", PHASE_2_FOUNDATIONS)
def test_phase_2_does_not_build_on_an_unaccepted_adr(number: str) -> None:
    """AC-PRE2-01: each ADR phase 2 builds on says Accepted."""
    status = _status(number)
    assert status.startswith("Accepted"), f"ADR-{number} is {status!r}"
