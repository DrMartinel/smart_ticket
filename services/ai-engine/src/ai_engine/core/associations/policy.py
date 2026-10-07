"""
The entity policy (`core/prompts/kb_entities.v*.yaml`, ADR-0018), selected by
`ENTITY_POLICY_VERSION`. Its `entity_types_guidance` goes to the extraction
model; the rest is applied when scoring. Loaded by the build only, so the
served app never parses it.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from ai_engine.core.associations.scoring import EntityPolicy
from ai_engine.core.prompts import PROMPT_DIR, check_version


@dataclass(frozen=True)
class LoadedPolicy:
    version: str
    guidance: str
    scoring: EntityPolicy


def load_entity_policy(version: str) -> LoadedPolicy:
    """Resolve "kb_entities.v1" to core/prompts/kb_entities.v1.yaml. A
    missing file or field fails before any article is sent to the model."""

    check_version(version)
    raw = yaml.safe_load((PROMPT_DIR / f"{version}.yaml").read_text(encoding="utf-8"))
    guidance = raw.get("entity_types_guidance") if isinstance(raw, dict) else None
    if not isinstance(guidance, str) or not guidance.strip():
        raise ValueError(f"entity policy {version!r} has no entity_types_guidance")
    return LoadedPolicy(
        version=version,
        guidance=guidance.strip(),
        scoring=EntityPolicy(
            allowed_types=frozenset(raw["allowed_types"]),
            aliases=dict(raw.get("aliases") or {}),
            stoplist=frozenset(raw.get("stoplist") or []),
        ),
    )
