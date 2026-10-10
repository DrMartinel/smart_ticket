"""
Rebuild the `authored_link` association source (ADR-0018) from the Markdown
links in every article's chunk text, replacing its rows in one transaction.

`entity_graph` is built offline by ai-engine and loaded with
`load_associations`; this command never calls a model.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.kb.models import AssociationSource, KbArticleAssociation


class Command(BaseCommand):
    help = "Rebuild the authored_link association source (ADR-0018) from the KB in the database."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--source", required=True, choices=[AssociationSource.AUTHORED_LINK])

    def handle(self, *args: Any, **options: Any) -> None:
        written = KbArticleAssociation.objects.rebuild_authored_links()
        self.stdout.write(self.style.SUCCESS(f"{options['source']}: {written} rows"))
