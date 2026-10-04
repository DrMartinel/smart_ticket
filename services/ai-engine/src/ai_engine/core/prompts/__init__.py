"""
Every prompt ai-engine sends, loaded once at import (spec §12.3: versioned
and eval-gated like code). Each `*_PROMPT_VERSION` setting selects the file
that runs, and modules import the constants below. A missing or malformed
file fails the boot, not the first ticket.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_engine.core.config import settings

PROMPT_DIR = Path(__file__).resolve().parent


def load_system_prompt(version: str) -> str:
    """Resolve a prompt version ("classify.v3") to core/prompts/classify.v3.md,
    without the file's leading `<!-- ... -->` changelog.

    The changelog is for people reading the file. Sent with the prompt, it
    cost every classify call ~875 tokens of version history (v7) inside a
    4096-token context, where long KB chunks already push some calls over
    (evals/HISTORY.md 2026-10-04 (4)). Only a comment that opens the file is
    removed: the instructions themselves are never touched."""

    _check_version(version)
    text = (PROMPT_DIR / f"{version}.md").read_text()
    if text.startswith("<!--"):
        end = text.find("-->")
        if end == -1:
            raise ValueError(f"prompt {version!r} opens a comment it never closes")
        text = text[end + len("-->") :].lstrip()
    return text


def load_question(version: str) -> dict[str, Any]:
    """Resolve a question version ("rerank_resolves.v1") to
    core/prompts/rerank_resolves.v1.json: a TypeSafe question object, sent
    as is."""

    _check_version(version)
    question = json.loads((PROMPT_DIR / f"{version}.json").read_text())
    if not isinstance(question, dict) or not question.get("instructions"):
        raise ValueError(f"question {version!r} has no instructions")
    return question


def _check_version(version: str) -> None:
    if "/" in version or "\\" in version or ".." in version:
        # Pre-emptive: AIRunRequest.prompt_version is caller-supplied. If
        # per-request prompt selection ever lands, it must not be able to
        # read arbitrary files off disk.
        raise ValueError(f"invalid prompt version: {version!r}")


# --- The prompts --------------------------------------------------------------

# InferNode's system prompt, the triage classification.
CLASSIFY_PROMPT = load_system_prompt(settings.prompt_version)
# Tier-2 PII NER's system prompt (ADR-0012).
PII_NER_PROMPT = load_system_prompt(settings.pii_ner_prompt_version)
# The question Jev answers per chunk (ADR-0015).
RERANK_QUESTION = load_question(settings.rerank_prompt_version)
