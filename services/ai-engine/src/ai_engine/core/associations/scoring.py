"""
Scoring for the `entity_graph` association source (ADR-0018): raw entity
mentions in, article-to-article rows out. Pure: no model, no database, no
LightRAG. It reads only the extractor-neutral `mentions.jsonl` shape, so the
extractor can change without touching it, and `build --rescore-only` can
re-run it after a policy change or a batch of deactivations for free.

Two articles are associated by the entities they share. Each shared entity
adds `ln(N / df)`, N the number of active articles and df the number of
active articles that mention it: a rare shared entity ("SES Sandbox", df 6)
says much more than a common one. An entity mentioned by more than
`hub_df_max` active articles links nothing ("Amazon SES", df 140): it would
connect half a guide to the other half.

The score only orders one article's targets. It is never compared with a
threshold (ADR-0005); core-api stores it, and ai-engine's read ranks by it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, order=True)
class Mention:
    """One entity named in one article, as extracted: the `mentions.jsonl`
    contract (demo_kb/README.md)."""

    entity: str
    type: str
    article_slug: str


@dataclass(frozen=True)
class EntityPolicy:
    """The scoring half of the entity policy (core/prompts/kb_entities.v*.yaml):
    which types count, which names are the same entity, which never link."""

    allowed_types: frozenset[str]
    aliases: Mapping[str, str]
    stoplist: frozenset[str]


@dataclass(frozen=True)
class AssociationRow:
    """One line of `entity_graph.jsonl`: one direction of one pair."""

    source_slug: str
    target_slug: str
    score: float
    evidence: tuple[str, ...]
    build_id: str


def apply_policy(mentions: Iterable[Mention], policy: EntityPolicy) -> list[Mention]:
    """Mentions of allowed types, with aliases folded into their canonical
    name, names that differ only in case merged, and stoplisted names
    dropped. Types, aliases and the stoplist are compared case-insensitively.

    Case variants ("AWS accounts", "AWS Accounts") are one entity: the
    extractor names the same concept differently from page to page (370 such
    names in the 2026-10-08 spike), and split apart each looks rarer than it
    is, so the pages sharing it would not be linked. The merged entity is
    spelled as the variant that sorts first, so a rebuild names it the same."""

    aliases = {alias.casefold(): name for alias, name in policy.aliases.items()}
    stoplist = {name.casefold() for name in policy.stoplist}
    allowed = {t.casefold() for t in policy.allowed_types}
    kept = [
        (aliases.get(m.entity.casefold(), m.entity), m)
        for m in mentions
        if m.type.casefold() in allowed
    ]
    spellings: dict[str, set[str]] = defaultdict(set)
    for name, _ in kept:
        spellings[name.casefold()].add(name)
    canonical = {folded: min(names) for folded, names in spellings.items()}
    return sorted(
        {
            Mention(entity=canonical[name.casefold()], type=m.type, article_slug=m.article_slug)
            for name, m in kept
            if name.casefold() not in stoplist
        }
    )


def score_associations(
    mentions: Iterable[Mention],
    active_slugs: set[str],
    *,
    hub_df_max: int,
    per_article_cap: int,
    build_id: str,
    method: Literal["idf_sum", "idf_cosine"] = "idf_sum",
) -> list[AssociationRow]:
    """Rows for every pair of articles sharing a non-hub entity, the top
    `per_article_cap` targets per source article, in a stable order.

    df and N count ACTIVE articles only, so scores describe the KB a ticket
    can reach. Inactive articles still get rows (ai-engine's read hides
    them until they are reactivated), but an entity no active article
    mentions has no df and links nothing.

    `method`: `idf_sum` adds `ln(N / df)` per shared entity. `idf_cosine`
    divides that by `sqrt(|A| * |B|)`, the two articles' entity counts: a
    catalogue page listing dozens of finding types otherwise outscores the
    page that remediates them just by sharing more entities (the 2026-10-08
    probe: 95-199 against 24)."""

    articles_by_entity: dict[str, set[str]] = defaultdict(set)
    entity_count: dict[str, int] = defaultdict(int)
    for m in mentions:
        articles_by_entity[m.entity].add(m.article_slug)
    for slugs in articles_by_entity.values():
        for slug in slugs:
            entity_count[slug] += 1

    n = len(active_slugs)
    pair_score: dict[tuple[str, str], float] = defaultdict(float)
    pair_evidence: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for entity, slugs in articles_by_entity.items():
        df = len(slugs & active_slugs)
        if df == 0 or df > hub_df_max or len(slugs) < 2:
            continue
        weight = math.log(n / df)
        for source in slugs:
            for target in slugs:
                if source != target:
                    pair_score[source, target] += weight
                    pair_evidence[source, target].append((weight, entity))

    targets: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for (source, target), score in pair_score.items():
        if method == "idf_cosine":
            score /= math.sqrt(entity_count[source] * entity_count[target])
        targets[source].append((score, target))

    rows: list[AssociationRow] = []
    for source in sorted(targets):
        # Highest score first; the target slug breaks ties, so a rebuild of
        # the same mentions writes the same file.
        ranked = sorted(targets[source], key=lambda st: (-st[0], st[1]))[:per_article_cap]
        for score, target in ranked:
            evidence = sorted(pair_evidence[source, target], key=lambda we: (-we[0], we[1]))
            rows.append(
                AssociationRow(
                    source_slug=source,
                    target_slug=target,
                    score=round(score, 4),
                    evidence=tuple(entity for _, entity in evidence),
                    build_id=build_id,
                )
            )
    return rows


def df_histogram(mentions: Iterable[Mention], active_slugs: set[str]) -> dict[int, int]:
    """How many entities have each df (active articles), for choosing
    `hub_df_max` from the spike check."""

    articles_by_entity: dict[str, set[str]] = defaultdict(set)
    for m in mentions:
        articles_by_entity[m.entity].add(m.article_slug)
    histogram: dict[int, int] = defaultdict(int)
    for slugs in articles_by_entity.values():
        histogram[len(slugs & active_slugs)] += 1
    return dict(sorted(histogram.items()))
