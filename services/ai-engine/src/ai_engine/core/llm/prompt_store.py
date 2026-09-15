"""
Prompt resolution — spec §12.3 (prompts are versioned and eval-gated like
code).

`infer.py` previously read `classify.v3.md` by a hardcoded filename at
module import time, which meant `settings.prompt_version` was a no-op:
bumping it changed the version reported in logs and responses while the
graph kept running the old file. CLAUDE.md says to bump the version in the
filename AND in core/config.py; this makes the second half actually do something.
"""

from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_system_prompt(version: str) -> str:
    """Resolve a prompt version ("classify.v3") to prompts/classify.v3.md.

    Called once at startup by the graph builder: a missing or renamed prompt
    should crash the process at boot — the way core-api exits on a malformed
    thresholds.yaml — rather than surfacing on the first ticket.
    """

    if "/" in version or "\\" in version or ".." in version:
        # Pre-emptive: AIRunRequest.prompt_version is caller-supplied. If
        # per-request prompt selection ever lands, it must not be able to
        # read arbitrary files off disk.
        raise ValueError(f"invalid prompt version: {version!r}")
    return (PROMPT_DIR / f"{version}.md").read_text()
