"""
Keeps what retrieval reads about KB articles current: their chunks, their
associations (ADR-0018) and which of them are active.
"""

from __future__ import annotations

import uuid

from django.db import models, transaction

from infrastructure.ai_engine import ai_engine

from apps.kb.models import AssociationSource, KbArticle, KbArticleAssociation, KbChunk
from apps.kb.utils.associations import build_id, link_scores, linked_urls
from apps.kb.utils.chunking import chunk_sections, rough_token_count


class ArticleIndexer:
    """Writes the chunks and associations retrieval reads, and which articles are active."""

    @transaction.atomic
    def ingest(self, article: KbArticle) -> list[KbChunk]:
        """Re-chunks and re-embeds `article`, and refreshes its associations (ADR-0025)."""

        KbChunk.objects.filter(article=article).delete()
        chunks: list[KbChunk] = []
        for i, piece in enumerate(chunk_sections(article.body)):
            # The embedding input: the article and section titles, then the chunk.
            context = "\n".join(t for t in (article.title, piece.section_title) if t)
            embedding = ai_engine.embed(f"{context}\n\n{piece.content}").vector
            chunk = KbChunk.objects.create(
                article=article,
                chunk_index=i,
                content=piece.content,
                section_title=KbChunk.stored_section_title(piece.section_title),
                token_count=rough_token_count(piece.content),
                embedding=embedding,
            )
            chunks.append(chunk)
        KbArticleAssociation.objects.filter(
            models.Q(source_article=article) | models.Q(target_article=article),
            source=AssociationSource.ENTITY_GRAPH,
        ).delete()
        self.rebuild_authored_links([article])
        return chunks

    @transaction.atomic
    def rebuild_authored_links(self, articles: list[KbArticle] | None = None) -> int:
        """Rebuilds the `authored_link` rows out of `articles`, or of every article."""

        article_by_url = dict(
            KbArticle.objects.exclude(source_url="").values_list("source_url", "id")
        )
        sources = (
            KbArticle.objects.exclude(source_url="")
            if articles is None
            else [a for a in articles if a.source_url]
        )
        base_url = {a.id: a.source_url for a in sources}
        contents: dict[uuid.UUID, list[str]] = {article_id: [] for article_id in base_url}
        for article_id, content in (
            KbChunk.objects.filter(article_id__in=base_url)
            .order_by("article_id", "chunk_index")
            .values_list("article_id", "content")
        ):
            contents[article_id].append(content)

        build = build_id(AssociationSource.AUTHORED_LINK)
        rows = [
            KbArticleAssociation(
                source_article_id=article_id,
                target_article_id=target,
                source=AssociationSource.AUTHORED_LINK,
                score=score,
                evidence=[href],
                build_id=build,
            )
            for article_id, url in base_url.items()
            for target, score, href in link_scores(
                linked_urls(url, contents[article_id]), article_by_url, own_id=article_id
            )
        ]
        replaced = KbArticleAssociation.objects.filter(source=AssociationSource.AUTHORED_LINK)
        if articles is not None:
            replaced = replaced.filter(source_article__in=[a.id for a in articles])
        replaced.delete()
        return len(KbArticleAssociation.objects.bulk_create(rows))

    @transaction.atomic
    def sync_active_from_source(self, loaded_slugs: set[str]) -> tuple[int, int]:
        """Deactivates the source-loaded articles not in `loaded_slugs` and
        reactivates the ones in it."""

        from_source = KbArticle.objects.exclude(source_url="")
        deactivated = (
            from_source.filter(is_active=True)
            .exclude(slug__in=loaded_slugs)
            .update(is_active=False)
        )
        reactivated = from_source.filter(is_active=False, slug__in=loaded_slugs).update(
            is_active=True
        )
        return deactivated, reactivated


# --- the indexer ---

indexer = ArticleIndexer()
