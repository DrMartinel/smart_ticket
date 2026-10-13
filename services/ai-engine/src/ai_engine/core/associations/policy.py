"""
The entity-graph policy, read from `core/prompts/kb_entity_graph.v*.yaml`.
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
    """The entity-graph prompt, reply bounds, link stripping and page aliases."""

    version: str
    instructions: str
    limits: ReplyLimits
    strip_links: bool
    aliases: dict[str, str]

    @classmethod
    def load(cls, version: str) -> EntityGraphPolicy:
        """Loads `core/prompts/<version>.yaml`."""

        check_version(version)
        raw = yaml.safe_load((PROMPT_DIR / f"{version}.yaml").read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not str(raw.get("instructions") or "").strip():
            raise ValueError(f"entity-graph policy {version!r} has no instructions")
        return cls(
            version=version,
            instructions=raw["instructions"].strip(),
            limits=ReplyLimits(**raw["reply_limits"]),
            strip_links=bool(raw["strip_links"]),
            aliases=dict(raw.get("aliases") or {}),
        )
