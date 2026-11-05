"""
Knowledge base — spec §3.2. This is where auto-reply AUTHORITY lives
(ADR-0002): `auto_reply_allowed` is a human decision, database-constrained
to require an approver, never something the LLM can grant itself.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Func, Value
from django.db.models.functions import Concat
from django.utils import timezone
from pgvector.django import VectorField

from apps.core.models import BaseModel
from apps.tickets.utils.router import RiskTier
from infrastructure.dtos import TicketCategory

from apps.accounts.models import User
from apps.kb.utils.chunking import chunk_sections


class KBGovernanceError(Exception):
    pass


def text_sha256(title: str, body: str) -> str:
    """The SHA-256 of a page's title and body, the text an auto-reply approval is pinned to."""
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()


class TextSha256(Func):
    """`text_sha256` of the row's title and body, computed by Postgres."""

    template = "ENCODE(SHA256(CONVERT_TO(%(expressions)s, 'UTF8')), 'hex')"
    output_field = models.CharField()

    def __init__(self) -> None:
        super().__init__(
            Concat(F("title"), Value("\n"), F("body"), output_field=models.TextField())
        )


class KbArticleQuerySet(models.QuerySet["KbArticle"]):
    def authorized(self) -> KbArticleQuerySet:
        """Active pages allowed to auto-reply whose text is the text a manager approved."""
        return (
            self.filter(is_active=True, auto_reply_allowed=True)
            .annotate(current_sha256=TextSha256())
            .filter(approved_text_sha256=F("current_sha256"))
        )


class KbArticleManager(models.Manager["KbArticle"]):
    def get_queryset(self) -> KbArticleQuerySet:
        return KbArticleQuerySet(self.model, using=self._db)

    def authorized(self) -> KbArticleQuerySet:
        return self.get_queryset().authorized()

    def create_and_ingest(
        self, *, slug: str, title: str, body: str, category: str, risk_tier: str
    ) -> KbArticle:
        """Creates a KB article and ingests it so retrieval can find it.

        Grants no auto-reply authority: `auto_reply_allowed` keeps its False
        default, and only `set_auto_reply_allowed` may change it (ADR-0002).
        """
        from apps.kb.utils.indexing import indexer

        article = self.create(
            slug=slug, title=title, body=body, category=category, risk_tier=risk_tier
        )
        # Committed before ingestion, not with it: if embedding fails, the article
        # is kept with no chunks (invisible to retrieval) and `/reingest` retries.
        indexer.ingest(article)
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
        from apps.kb.utils.indexing import indexer

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
            indexer.ingest(article, graph_rebuild=None)
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
            indexer.ingest(article, graph_rebuild=None)
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
    # The SHA-256 of the title and body the approving manager read (F6 BR-F6-05).
    approved_text_sha256 = models.CharField(max_length=64, null=True, blank=True)
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

    def text_sha256(self) -> str:
        return text_sha256(self.title, self.body)

    def is_authorized(self) -> bool:
        """Whether the page may be cited by an auto-reply: allowed, active, and its text is the
        text that was approved."""
        return (
            self.is_active
            and self.auto_reply_allowed
            and self.approved_text_sha256 == self.text_sha256()
        )

    def chunks_are_current(self) -> bool:
        """Whether the stored chunks are exactly what `chunk_sections` makes
        of the body now. Text only, no embedding call, so it is cheap to ask
        of every article on a reload."""
        stored = list(self.chunks.order_by("chunk_index").values_list("section_title", "content"))
        expected = [
            (KbChunk.stored_section_title(c.section_title), c.content)
            for c in chunk_sections(self.body)
        ]
        return stored == expected

    @transaction.atomic
    def set_auto_reply_allowed(self, *, allowed: bool, actor: User, reason: str) -> KbArticle:
        """The only legitimate way to flip `auto_reply_allowed`. Spec §15 Q3 /
        ADR-0002: manager role required, reason mandatory, logged."""

        from apps.accounts.utils.access import Access
        from apps.accounts.utils.catalog import Permission

        if not Access.of(actor).holds(Permission.KB_AUTHORITY_GRANT):
            raise KBGovernanceError("only manager-role users may change auto_reply_allowed")
        if not reason or not reason.strip():
            raise KBGovernanceError("reason is required")

        old_value = str(self.auto_reply_allowed)
        self.auto_reply_allowed = allowed
        if allowed:
            self.approved_by = actor
            self.approved_at = timezone.now()
            self.approved_text_sha256 = self.text_sha256()
        self.version += 1
        self.save(
            update_fields=[
                "auto_reply_allowed",
                "approved_by",
                "approved_at",
                "approved_text_sha256",
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
        from apps.accounts.utils.access import Access
        from apps.accounts.utils.catalog import Permission

        if not Access.of(actor).holds(Permission.KB_AUTHORITY_RISK_TIER):
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
    # Lexical search runs on a pg_search BM25 index over content and
    # section_title (ADR-0013), declared in infra/migrations/sql/0005 because
    # the ORM can't express it. There is deliberately no tsvector column.

    @staticmethod
    def stored_section_title(title: str | None) -> str | None:
        """Cuts a section title to how `section_title` stores it."""
        return (title or "")[:255] or None

    class Meta(BaseModel.Meta):
        db_table = "kb_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["article", "chunk_index"], name="uq_kb_chunk_article_index"
            ),
        ]


class AssociationSource(models.TextChoices):
    """Where an association came from (ADR-0018)."""

    AUTHORED_LINK = "authored_link"
    # Pages a page names as where a problem's fix is written (offline build).
    ENTITY_GRAPH = "entity_graph"


class KbArticleAssociation(BaseModel):
    """One article pointing at another, for link expansion (ADR-0014
    decision 1, ADR-0018, ADR-0025)."""

    source_article = models.ForeignKey(
        KbArticle, on_delete=models.CASCADE, related_name="associations_out"
    )
    target_article = models.ForeignKey(
        KbArticle, on_delete=models.CASCADE, related_name="associations_in"
    )
    source = models.CharField(max_length=20, choices=AssociationSource.choices)
    # Orders one seed's targets within one source, higher first (ADR-0018).
    score = models.FloatField()
    # The link href, or the symptom -> remedy pairs behind the edge.
    evidence = models.JSONField(default=list)
    reviewed = models.BooleanField(default=False)
    # The page on either end was re-ingested since the build that wrote the row (F11).
    stale = models.BooleanField(default=False, db_default=False)
    # The build that produced the row (source, policy version, pairs, date).
    build_id = models.CharField(max_length=200)

    class Meta(BaseModel.Meta):
        db_table = "kb_article_associations"
        constraints = [
            models.UniqueConstraint(
                fields=["source_article", "target_article", "source"],
                name="uq_kb_association_pair_source",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_article=models.F("target_article")),
                name="chk_kb_association_not_self",
            ),
        ]
        indexes = [
            models.Index(
                "source_article",
                "source",
                models.F("score").desc(),
                name="idx_kb_association_seed",
            ),
        ]


class OverrideAction(StrEnum):
    HIDE = "hide"
    ADD = "add"


class KbAssociationOverride(BaseModel):
    """A KB editor's correction to link expansion between two pages, read by ai-engine and kept
    across rebuilds (F11, ADR-0037)."""

    source_article = models.ForeignKey(
        KbArticle, on_delete=models.CASCADE, related_name="overrides_out"
    )
    target_article = models.ForeignKey(
        KbArticle, on_delete=models.CASCADE, related_name="overrides_in"
    )
    action = models.CharField(max_length=10, choices=[(a.value, a.value) for a in OverrideAction])
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "kb_association_overrides"
        constraints = [
            models.UniqueConstraint(
                fields=["source_article", "target_article"], name="uq_kb_override_pair"
            ),
            models.CheckConstraint(
                condition=~models.Q(source_article=models.F("target_article")),
                name="chk_kb_override_not_self",
            ),
        ]


class RebuildReason(StrEnum):
    PUBLISH = "publish"
    MANUAL = "manual"


class RebuildState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class KbGraphRebuildRequest(BaseModel):
    """A page whose entity-graph edges the next `--pending` build replaces (F11, ADR-0037)."""

    article = models.ForeignKey(
        KbArticle, on_delete=models.CASCADE, related_name="graph_rebuild_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    reason = models.CharField(max_length=10, choices=[(r.value, r.value) for r in RebuildReason])
    state = models.CharField(
        max_length=10,
        choices=[(s.value, s.value) for s in RebuildState],
        default=RebuildState.PENDING.value,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)
    build_id = models.CharField(max_length=200, blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "kb_graph_rebuild_requests"
        constraints = [
            models.UniqueConstraint(
                fields=["article"],
                condition=models.Q(state="pending"),
                name="uq_kb_rebuild_one_pending",
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


class DraftKind(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    RETIRE = "retire"


class DraftState(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    CONFLICT = "conflict"


EDITABLE_DRAFT_STATES = (DraftState.DRAFT.value, DraftState.CHANGES_REQUESTED.value)


class KbDraftQuerySet(models.QuerySet["KbDraft"]):
    def awaiting_authority(self) -> KbDraftQuerySet:
        """Published drafts whose page still needs a manager's grant, re-grant or tier decision."""
        return self.filter(
            state=DraftState.PUBLISHED.value,
            authority_pending=True,
            article__is_active=True,
        )


class KbDraft(BaseModel):
    """A new page, an edit or a retirement before a second person approves it (ADR-0036). Never
    read by ai-engine."""

    kind = models.CharField(max_length=10, choices=[(k.value, k.value) for k in DraftKind])
    article = models.ForeignKey(
        KbArticle, on_delete=models.SET_NULL, null=True, blank=True, related_name="drafts"
    )
    slug = models.CharField(max_length=128)
    title = models.CharField(max_length=255)
    body = models.TextField()
    category = models.CharField(max_length=20, choices=[(c.value, c.value) for c in TicketCategory])
    proposed_risk_tier = models.CharField(
        max_length=10, choices=[(r.value, r.value) for r in RiskTier], default=RiskTier.HIGH.value
    )
    change_note = models.TextField(blank=True, default="")
    state = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in DraftState],
        default=DraftState.DRAFT.value,
    )
    base_version = models.IntegerField(null=True, blank=True)
    # The live page's text when the draft started: a change to it is a conflict.
    base_text_sha256 = models.CharField(max_length=64, blank=True, default="")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    review_comment = models.TextField(blank=True, default="")
    gap_cluster = models.ForeignKey(
        "KbGapCluster", on_delete=models.SET_NULL, null=True, blank=True, related_name="drafts"
    )
    # The live page's title and body this draft replaced, for the authority queue's diff.
    previous_title = models.CharField(max_length=255, blank=True, default="")
    previous_body = models.TextField(blank=True, default="")
    # Published, and a manager still has to decide the page's authority or tier.
    authority_pending = models.BooleanField(default=False)
    authority_reason = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = KbDraftQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        db_table = "kb_drafts"
        indexes = [models.Index(fields=["state", "updated_at"], name="idx_kb_drafts_state")]

    def is_editable(self) -> bool:
        return self.state in EDITABLE_DRAFT_STATES


class KbGapReport(BaseModel):
    """One weekly grouping of refused tickets (F6 UC-F6-06)."""

    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    tickets_considered = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "kb_gap_reports"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["window_start", "window_end"], name="uniq_gap_window")
        ]


class GapLabel(StrEnum):
    GAP = "gap"
    UPDATE = "update"


class GapState(StrEnum):
    OPEN = "open"
    DRAFTED = "drafted"
    DISMISSED = "dismissed"


class KbGapCluster(BaseModel):
    """Refused tickets on one topic, with the nearest live page."""

    report = models.ForeignKey(KbGapReport, on_delete=models.CASCADE, related_name="clusters")
    label = models.CharField(max_length=10, choices=[(g.value, g.value) for g in GapLabel])
    size = models.IntegerField()
    sample_tickets = models.JSONField(default=list)
    nearest_article = models.ForeignKey(
        KbArticle, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    nearest_similarity = models.FloatField(null=True, blank=True)
    centroid = VectorField(dimensions=1024, null=True, blank=True)
    state = models.CharField(
        max_length=10,
        choices=[(g.value, g.value) for g in GapState],
        default=GapState.OPEN.value,
    )
    dismiss_reason = models.TextField(blank=True, default="")
    dismissed_until = models.DateTimeField(null=True, blank=True)
    tickets = models.ManyToManyField(
        "tickets.Ticket", through="KbGapClusterTicket", related_name="+"
    )

    class Meta(BaseModel.Meta):
        db_table = "kb_gap_clusters"
        ordering = ["-size"]


class KbGapClusterTicket(BaseModel):
    cluster = models.ForeignKey(KbGapCluster, on_delete=models.CASCADE)
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="+")

    class Meta(BaseModel.Meta):
        db_table = "kb_gap_cluster_tickets"
        constraints = [
            models.UniqueConstraint(fields=["cluster", "ticket"], name="uniq_gap_cluster_ticket")
        ]
