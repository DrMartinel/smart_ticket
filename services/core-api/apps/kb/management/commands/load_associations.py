"""
Load an association file built offline (ADR-0018), today ai-engine's
`entity_graph.jsonl`, into `kb_article_associations`, replacing that
source's rows in one transaction.

The file is keyed by slug and may be older than the database: a slug it
names may have been deleted since. Unknown slugs and self-pairs are skipped
and counted, never guessed at. Inactive articles are loaded: ai-engine's
read hides them, so reactivating one needs no reload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation


class AssociationLine(BaseModel):
    """One line of the file: one direction of one pair."""

    model_config = ConfigDict(extra="forbid")

    source_slug: str = Field(min_length=1)
    target_slug: str = Field(min_length=1)
    score: float
    evidence: list[str]
    build_id: str = Field(min_length=1)


class Command(BaseCommand):
    help = "Load an offline-built association file (ADR-0018) into kb_article_associations."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path", help="the .jsonl file, e.g. demo_kb/associations/entity_graph.jsonl"
        )
        parser.add_argument("--source", required=True, choices=[AssociationSource.ENTITY_GRAPH])

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"{path} not found")
        lines = []
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not text.strip():
                continue
            try:
                lines.append(AssociationLine.model_validate_json(text))
            except ValidationError as e:
                # A malformed line means a broken file, not one bad edge:
                # load nothing rather than part of it.
                raise CommandError(f"{path}:{number} is invalid:\n{e}") from e

        written, counts = load_association_lines(lines, options["source"])
        self.stdout.write(
            self.style.SUCCESS(
                f"{options['source']}: {written} rows; skipped "
                + ", ".join(f"{k}={v}" for k, v in counts.items())
            )
        )


def load_association_lines(lines: list[AssociationLine], source: str) -> tuple[int, dict[str, int]]:
    """Replaces `source`'s rows with `lines`. Returns the rows written and
    what was skipped."""

    article_by_slug = dict(KbArticle.objects.values_list("slug", "id"))
    counts = {"unknown_slug": 0, "self_pair": 0}
    rows = []
    for line in lines:
        source_id = article_by_slug.get(line.source_slug)
        target_id = article_by_slug.get(line.target_slug)
        if source_id is None or target_id is None:
            counts["unknown_slug"] += 1
            continue
        if source_id == target_id:
            counts["self_pair"] += 1
            continue
        rows.append(
            KbArticleAssociation(
                source_article_id=source_id,
                target_article_id=target_id,
                source=source,
                score=line.score,
                evidence=line.evidence,
                build_id=line.build_id,
            )
        )
    return KbArticleAssociation.objects.replace_source(source, rows), counts
