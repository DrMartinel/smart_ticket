"""
The entity-graph policy (`core/prompts/kb_entity_graph.v*.yaml`), selected
by `ENTITY_GRAPH_POLICY_VERSION`. Loaded by the build only.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from ai_engine.core.prompts import PROMPT_DIR, check_version


@dataclass(frozen=True)
class ReplyLimits:
    """Bounds on one reply, checked when it is parsed."""

    max_pairs_per_section: int
    symptom_max_chars: int
    remedy_max_chars: int
    page_max_chars: int


@dataclass(frozen=True)
class EntityGraphPolicy:
    version: str
    instructions: str
    limits: ReplyLimits
    strip_links: bool
    aliases: dict[str, str]


def load_policy(version: str) -> EntityGraphPolicy:
    """Resolve "kb_entity_graph.v1" to core/prompts/kb_entity_graph.v1.yaml. A
    missing file or field fails before any section is sent to the model."""

    check_version(version)
    raw = yaml.safe_load((PROMPT_DIR / f"{version}.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not str(raw.get("instructions") or "").strip():
        raise ValueError(f"entity-graph policy {version!r} has no instructions")
    return EntityGraphPolicy(
        version=version,
        instructions=raw["instructions"].strip(),
        limits=ReplyLimits(**raw["reply_limits"]),
        strip_links=bool(raw["strip_links"]),
        aliases=dict(raw.get("aliases") or {}),
    )
