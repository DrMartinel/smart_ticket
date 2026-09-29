"""
Knowledge base — spec §3.2. This is where auto-reply AUTHORITY lives
(ADR-0002): `auto_reply_allowed` is a human decision, database-constrained
to require an approver, never something the LLM can grant itself.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.search import SearchVectorField
from django.db import models, transaction
from apps.core.models import BaseModel
from django.utils import timezone
from pgvector.django import VectorField

from apps.tickets.utils.router import RiskTier
from infrastructure.ai_engine import TicketCategory

from apps.accounts.models import User
from apps.kb.utils import chunk_body, rough_token_count
from infrastructure.embeddings import embed_text


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


class KbArticle(BaseModel):
    slug = models.CharField(max_length=32, unique=True)  # KB-0142
    title = models.CharField(max_length=255)
    body = models.TextField()
    category = models.CharField(max_length=20, choices=[(c.value, c.value) for c in TicketCategory])

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

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[KbArticleManager] = KbArticleManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    def __str__(self) -> str:
        return f"{self.slug}: {self.title}"

    @transaction.atomic
    def ingest(self) -> list[KbChunk]:
        """(Re)chunks and (re)embeds this article. Existing chunks are
        replaced wholesale — simplest correct behavior for a KB whose update
        cadence is "occasional edits by a KB owner", not high-frequency."""

        KbChunk.objects.filter(article=self).delete()
        pieces = chunk_body(self.body)
        chunks: list[KbChunk] = []
        for i, content in enumerate(pieces):
            embedding = embed_text(content)
            chunk = KbChunk.objects.create(
                article=self,
                chunk_index=i,
                content=content,
                section_title=None,
                token_count=rough_token_count(content),
                embedding=embedding,
            )
            chunks.append(chunk)
        # tsv is maintained by the Postgres trigger on INSERT/UPDATE OF content
        # (infra/migrations/sql/0003_constraints_and_triggers.sql), fired by
        # the .create() calls above — no separate step needed here.
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


class KbChunk(BaseModel):
    article = models.ForeignKey(KbArticle, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.IntegerField()
    content = models.TextField()
    section_title = models.CharField(max_length=255, null=True, blank=True)
    token_count = models.IntegerField()
    embedding = VectorField(dimensions=1024, null=True, blank=True)
    # tsv is maintained by a Postgres trigger (0003_constraints_and_triggers.sql),
    # not by Django, so BM25 (ts_rank_cd) stays correct regardless of write path.
    tsv = SearchVectorField(null=True, blank=True, editable=False)

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
