"""
Prompt resolution — spec §12.3 (prompts are versioned and eval-gated like
code). Makes `settings.prompt_version` select the file that actually runs.
"""

from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


def load_system_prompt(version: str) -> str:
    """Resolve a prompt version ("classify.v3") to core/prompts/classify.v3.md.

    Called at startup, so a missing prompt crashes the boot rather than
    the first ticket.
    """

    if "/" in version or "\\" in version or ".." in version:
        # Pre-emptive: AIRunRequest.prompt_version is caller-supplied. If
        # per-request prompt selection ever lands, it must not be able to
        # read arbitrary files off disk.
        raise ValueError(f"invalid prompt version: {version!r}")
    return (PROMPT_DIR / f"{version}.md").read_text()
