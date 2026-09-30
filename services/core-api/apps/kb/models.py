"""
Knowledge base — spec §3.2. This is where auto-reply AUTHORITY lives
(ADR-0002): `auto_reply_allowed` is a human decision, database-constrained
to require an approver, never something the LLM can grant itself.
"""

from __future__ import annotations


from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from pgvector.django import VectorField

from apps.core.models import BaseModel
from apps.tickets.utils.router import RiskTier
from infrastructure.dtos import TicketCategory
from infrastructure.ai_engine import ai_engine

from apps.accounts.models import User
from apps.kb.utils import chunk_sections, rough_token_count


class KBGovernanceError(Exception):
    pass


class KbArticleManager(models.Manager["KbArticle"]):
    def create_and_ingest(
        self, *, slug: str, title: str, body: str, category: str, risk_tier: str
    ) -> KbArticle:
        """Creates a KB article and ingests it so retrieval can find it.

        Grants no auto-reply authority: `auto_reply_allowed` keeps its False
        default, and only `set_auto_reply_allowed` may change it (ADR-0002).
        """
        article = self.create(
            slug=slug, title=title, body=body, category=category, risk_tier=risk_tier
        )
        # Committed before ingestion, not with it: if embedding fails, the article
        # is kept with no chunks (invisible to retrieval) and `/reingest` retries.
        article.ingest()
        return article

    def upsert_from_source(
        self,
        *,
        slug: str,
        title: str,
        body: str,
        category: str,
        risk_tier: str,
        source_url: str,
    ) -> tuple[KbArticle, bool]:
        """Creates or refreshes an article from an external source such as
        the demo KB snapshot. Returns `(article, changed)`.

        An unchanged body is not re-embedded, so reloading a snapshot is
        cheap. `risk_tier` applies only on creation: after that it is a
        governed field, changed through `set_risk_tier` with a logged reason,
        so a reload can't quietly undo a manager's decision. Never touches
        `auto_reply_allowed` (ADR-0002).
        """
        article = self.filter(slug=slug).first()
        if article is None:
            article = self.create(
                slug=slug,
                title=title,
                body=body,
                category=category,
                risk_tier=risk_tier,
                source_url=source_url,
            )
            article.ingest()
            return article, True
        fields_changed = (article.title, article.body, article.category, article.source_url) != (
            title,
            body,
            category,
            source_url,
        )
        # The title is part of every chunk's embedding input (see ingest),
        # so a new title needs new vectors even when the body is the same.
        text_changed = (article.title, article.body) != (title, body)
        if fields_changed:
            article.title, article.body = title, body
            article.category, article.source_url = category, source_url
            article.version += 1
            article.save(
                update_fields=["title", "body", "category", "source_url", "version", "updated_at"]
            )
        # Stored chunks that differ from what the current chunker makes mean
        # an earlier ingest failed after the row was committed (no chunks;
        # see create_and_ingest) or ran under an older chunker. Either way
        # retrieval is searching text the article no longer splits into.
        if text_changed or not article.chunks_are_current():
            article.ingest()
            return article, True
        return article, fields_changed


class KbArticle(BaseModel):
    # KB-0142, or `iam.id_credentials_mfa` for the demo KB.
    # Used in API paths, so never contains "/".
    slug = models.CharField(max_length=128, unique=True)
    title = models.CharField(max_length=255)
    body = models.TextField()
    category = models.CharField(max_length=20, choices=[(c.value, c.value) for c in TicketCategory])
    # Where the text came from, for articles ingested from external docs.
    # AWS documentation is CC BY-SA 4.0: attribution travels with the text.
    source_url = models.URLField(max_length=500, blank=True, default="")

    # ══ AUTHORITY: a human decides, not the LLM ══
    auto_reply_allowed = models.BooleanField(default=False)
    risk_tier = models.CharField(
        max_length=10, choices=[(r.value, r.value) for r in RiskTier], default=RiskTier.HIGH.value
    )
    requires_approval_from = models.CharField(max_length=30, null=True, blank=True)  # role slug
    runbook_id = models.CharField(max_length=64, null=True, blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        # Explicit db_column: chk_autoreply_approved (raw SQL, spec §3.2)
        # checks `approved_by IS NOT NULL` against this exact column name,
        # not Django's default `approved_by_id`.
        db_column="approved_by",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        db_table = "kb_articles"
        # chk_autoreply_approved CHECK constraint is added by
        # infra/migrations/sql/0003_constraints_and_triggers.sql.

    objects = KbArticleManager()

    def __str__(self) -> str:
        return f"{self.slug}: {self.title}"

    def chunks_are_current(self) -> bool:
        """Whether the stored chunks are exactly what `chunk_sections` makes
        of the body now. Text only, no embedding call, so it is cheap to ask
        of every article on a reload."""
        stored = list(self.chunks.order_by("chunk_index").values_list("section_title", "content"))
        expected = [
            (_stored_section_title(c.section_title), c.content) for c in chunk_sections(self.body)
        ]
        return stored == expected

    @transaction.atomic
    def ingest(self) -> list[KbChunk]:
        """(Re)chunks and (re)embeds this article. Existing chunks are
        replaced wholesale — simplest correct behavior for a KB whose update
        cadence is "occasional edits by a KB owner", not high-frequency."""

        KbChunk.objects.filter(article=self).delete()
        chunks: list[KbChunk] = []
        for i, piece in enumerate(chunk_sections(self.body)):
            # The article and section titles go into the embedding input but
            # not into `content`: a chunk from the middle of a long page
            # ("Choose Next, then Save") means nothing without them, while
            # `content` must stay the exact text the model may quote.
            context = "\n".join(t for t in (self.title, piece.section_title) if t)
            embedding = ai_engine.embed(f"{context}\n\n{piece.content}").vector
            chunk = KbChunk.objects.create(
                article=self,
                chunk_index=i,
                content=piece.content,
                section_title=_stored_section_title(piece.section_title),
                token_count=rough_token_count(piece.content),
                embedding=embedding,
            )
            chunks.append(chunk)
        # The BM25 index (idx_chunk_bm25, infra/migrations/sql/0005) is
        # maintained by pg_search on insert, so no separate step is needed.
        return chunks

    @transaction.atomic
    def set_auto_reply_allowed(self, *, allowed: bool, actor: User, reason: str) -> KbArticle:
        """The only legitimate way to flip `auto_reply_allowed`. Spec §15 Q3 /
        ADR-0002: manager role required, reason mandatory, logged."""

        if not actor.is_manager:
            raise KBGovernanceError("only manager-role users may change auto_reply_allowed")
        if not reason or not reason.strip():
            raise KBGovernanceError("reason is required")

        old_value = str(self.auto_reply_allowed)
        self.auto_reply_allowed = allowed
        if allowed:
            self.approved_by = actor
            self.approved_at = timezone.now()
        self.version += 1
        self.save(
            update_fields=[
                "auto_reply_allowed",
                "approved_by",
                "approved_at",
                "version",
                "updated_at",
            ]
        )

        KbAuthorityLog.objects.create(
            article=self,
            field="auto_reply_allowed",
            old_value=old_value,
            new_value=str(allowed),
            actor=actor,
            reason=reason,
        )
        return self

    @transaction.atomic
    def set_risk_tier(self, *, risk_tier: str, actor: User, reason: str) -> KbArticle:
        if not actor.is_manager:
            raise KBGovernanceError("only manager-role users may change risk_tier")
        if not reason or not reason.strip():
            raise KBGovernanceError("reason is required")

        old_value = self.risk_tier
        self.risk_tier = risk_tier
        self.save(update_fields=["risk_tier", "updated_at"])

        KbAuthorityLog.objects.create(
            article=self,
            field="risk_tier",
            old_value=old_value,
            new_value=risk_tier,
            actor=actor,
            reason=reason,
        )
        return self


def _stored_section_title(title: str | None) -> str | None:
    """As `kb_chunks.section_title` stores it: at most 255 characters, and
    None for no heading. `ingest` writes it and `chunks_are_current` compares
    against it, so both must go through here."""
    return (title or "")[:255] or None


class KbChunk(BaseModel):
    article = models.ForeignKey(KbArticle, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.IntegerField()
    content = models.TextField()
    section_title = models.CharField(max_length=255, null=True, blank=True)
    token_count = models.IntegerField()
    embedding = VectorField(dimensions=1024, null=True, blank=True)
    # Lexical search runs on a pg_search BM25 index over content and
    # section_title (ADR-0013), declared in infra/migrations/sql/0005 because
    # the ORM can't express it. There is deliberately no tsvector column.

    class Meta(BaseModel.Meta):
        db_table = "kb_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["article", "chunk_index"], name="uq_kb_chunk_article_index"
            ),
        ]


class KbAuthorityLog(BaseModel):
    """Mandatory audit trail for `auto_reply_allowed` / `risk_tier`
    changes — spec §3.2. Every flip requires a human, a role check, and a
    reason (enforced in `KbArticle.set_auto_reply_allowed` / `set_risk_tier`, not
    just here)."""

    article = models.ForeignKey(KbArticle, on_delete=models.CASCADE, related_name="authority_log")
    field = models.CharField(max_length=40)  # auto_reply_allowed | risk_tier
    old_value = models.CharField(max_length=100, null=True, blank=True)
    new_value = models.CharField(max_length=100, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "kb_authority_log"
