"""
Rebuild one association source from what is already in the database
(ADR-0018), replacing that source's rows in one transaction:

- `authored_link`: Markdown links in every article's chunk text.
- `embedding_neighbour`: each article's nearest articles by centroid of its
  stored chunk vectors, `associations.embedding_neighbour_k` in
  thresholds.yaml.

`entity_graph` is built offline by ai-engine and loaded with
`load_associations`; this command never calls a model.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.kb.models import AssociationSource, KbArticleAssociation


class Command(BaseCommand):
    help = "Rebuild one association source (ADR-0018) from the KB in the database."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source",
            required=True,
            choices=[AssociationSource.AUTHORED_LINK, AssociationSource.EMBEDDING_NEIGHBOUR],
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["source"] == AssociationSource.AUTHORED_LINK:
            written = KbArticleAssociation.objects.rebuild_authored_links()
        else:
            written = KbArticleAssociation.objects.rebuild_embedding_neighbours(
                k=settings.THRESHOLDS.associations.embedding_neighbour_k
            )
        self.stdout.write(self.style.SUCCESS(f"{options['source']}: {written} rows"))
