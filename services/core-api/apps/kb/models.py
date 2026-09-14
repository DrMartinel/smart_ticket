"""
Knowledge base — spec §3.2. This is where auto-reply AUTHORITY lives
(ADR-0002): `auto_reply_allowed` is a human decision, database-constrained
to require an approver, never something the LLM can grant itself.
"""

from django.conf import settings
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from pgvector.django import VectorField

from contracts.enums import RiskTier, TicketCategory


class KbArticle(models.Model):
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

    class Meta:
        db_table = "kb_articles"
        # chk_autoreply_approved CHECK constraint is added by
        # infra/migrations/sql/0003_constraints_and_triggers.sql.

    def __str__(self) -> str:
        return f"{self.slug}: {self.title}"


class KbChunk(models.Model):
    article = models.ForeignKey(KbArticle, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.IntegerField()
    content = models.TextField()
    section_title = models.CharField(max_length=255, null=True, blank=True)
    token_count = models.IntegerField()
    embedding = VectorField(dimensions=1024, null=True, blank=True)
    # tsv is maintained by a Postgres trigger (0003_constraints_and_triggers.sql),
    # not by Django, so BM25 (ts_rank_cd) stays correct regardless of write path.
    tsv = SearchVectorField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "kb_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["article", "chunk_index"], name="uq_kb_chunk_article_index"
            ),
        ]


class KbAuthorityLog(models.Model):
    """Mandatory audit trail for `auto_reply_allowed` / `risk_tier`
    changes — spec §3.2. Every flip requires a human, a role check, and a
    reason (enforced in apps/kb/services.py, not just here)."""

    article = models.ForeignKey(KbArticle, on_delete=models.CASCADE, related_name="authority_log")
    field = models.CharField(max_length=40)  # auto_reply_allowed | risk_tier
    old_value = models.CharField(max_length=100, null=True, blank=True)
    new_value = models.CharField(max_length=100, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "kb_authority_log"
