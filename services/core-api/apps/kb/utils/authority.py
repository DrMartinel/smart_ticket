"""Auto-reply authority after F6: the queue of pages a manager must decide, single and bulk
grants, and the authority log."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import F, QuerySet

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.kb.models import (
    KBGovernanceError,
    KbArticle,
    KbAuthorityLog,
    KbDraft,
    TextSha256,
)
from apps.kb.utils.drafts import AuthorityReason, KbError, KbRefusal
from apps.tickets.utils.router import RiskTier


@dataclass
class QueueItem:
    article: KbArticle
    reason: str
    draft: KbDraft | None


class KbAuthority:
    """A manager's decisions on which page text the auto-reply may cite."""

    def queue(self) -> list[QueueItem]:
        """Pages published by a draft and still undecided, then pages whose text no longer matches
        the approved text."""
        items = [
            QueueItem(d.article, d.authority_reason, d)
            for d in KbDraft.objects.awaiting_authority()
            .select_related("article")
            .order_by("published_at")
            if d.article is not None
        ]
        queued = {i.article.id for i in items}
        stale = (
            KbArticle.objects.filter(is_active=True, auto_reply_allowed=True)
            .annotate(current_sha256=TextSha256())
            .exclude(approved_text_sha256=F("current_sha256"))
            .exclude(id__in=queued)
            .order_by("slug")
        )
        return items + [QueueItem(a, AuthorityReason.REGRANT.value, None) for a in stale]

    def article(self, slug: str) -> KbArticle:
        article = KbArticle.objects.filter(slug=slug).first()
        if article is None:
            raise KbError(404, KbRefusal.ARTICLE_NOT_FOUND, "KB article not found")
        return article

    @transaction.atomic
    def set_allowed(self, slug: str, actor: User, allowed: bool, reason: str) -> KbArticle:
        """Grants or revokes through `set_auto_reply_allowed`, settling the page's queue item."""
        article = KbArticle.objects.select_for_update().filter(slug=slug).first()
        if article is None:
            raise KbError(404, KbRefusal.ARTICLE_NOT_FOUND, "KB article not found")
        if allowed and not article.is_active:
            raise KbError(409, KbRefusal.NOT_EDITABLE, "a retired page can't be granted")
        self.apply(article, actor, allowed, reason)
        return article

    @transaction.atomic
    def set_tier(self, slug: str, actor: User, risk_tier: str, reason: str) -> KbArticle:
        article = KbArticle.objects.select_for_update().filter(slug=slug).first()
        if article is None:
            raise KbError(404, KbRefusal.ARTICLE_NOT_FOUND, "KB article not found")
        try:
            article.set_risk_tier(risk_tier=risk_tier, actor=actor, reason=reason)
        except KBGovernanceError as e:
            raise KbError(403, KbRefusal.NOT_ALLOWED, str(e)) from e
        self.settle(article)
        return article

    @transaction.atomic
    def bulk(self, slugs: list[str], actor: User, allowed: bool, reason: str) -> int:
        """All the pages or none; high-risk pages are never granted in bulk (ADR-0027)."""
        articles = list(KbArticle.objects.select_for_update().filter(slug__in=set(slugs)))
        missing = sorted(set(slugs) - {a.slug for a in articles})
        if missing:
            raise KbError(404, KbRefusal.ARTICLE_NOT_FOUND, "KB article not found", missing)
        if allowed:
            high = sorted(a.slug for a in articles if a.risk_tier == RiskTier.HIGH.value)
            if high:
                raise KbError(
                    422,
                    KbRefusal.HIGH_RISK_BULK,
                    "high-risk pages are approved one at a time",
                    high,
                )
            retired = sorted(a.slug for a in articles if not a.is_active)
            if retired:
                raise KbError(
                    409, KbRefusal.NOT_EDITABLE, "a retired page can't be granted", retired
                )
        for article in articles:
            self.apply(article, actor, allowed, reason)
        return len(articles)

    def apply(self, article: KbArticle, actor: User, allowed: bool, reason: str) -> None:
        try:
            article.set_auto_reply_allowed(allowed=allowed, actor=actor, reason=reason)
        except KBGovernanceError as e:
            code = KbRefusal.NOT_ALLOWED if not actor.is_manager else KbRefusal.REASON_REQUIRED
            raise KbError(403 if code is KbRefusal.NOT_ALLOWED else 422, code, str(e)) from e
        AuditLog.objects.record(
            "kb_authority_granted" if allowed else "kb_authority_revoked",
            actor_type="human",
            actor_id=actor.id,
            payload={"slug": article.slug, "reason": reason},
        )
        self.settle(article)

    def settle(self, article: KbArticle) -> None:
        """A manager decided the page: its published drafts leave the queue."""
        KbDraft.objects.awaiting_authority().filter(article=article).update(authority_pending=False)

    # ── the log (UC-F6-05) ──

    def log(
        self,
        *,
        slug: str | None = None,
        actor: str | None = None,
        field: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> QuerySet[KbAuthorityLog]:
        rows = KbAuthorityLog.objects.select_related("article", "actor").order_by("-changed_at")
        if slug:
            rows = rows.filter(article__slug=slug)
        if actor:
            rows = rows.filter(actor__username=actor)
        if field:
            rows = rows.filter(field=field)
        if since:
            rows = rows.filter(changed_at__gte=since)
        if until:
            rows = rows.filter(changed_at__lt=until)
        return rows

    def export(self, viewer: User, filters: dict[str, Any]) -> str:
        """The filtered log as CSV; the export is audited."""
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            ["changed_at", "slug", "field", "old_value", "new_value", "actor", "reason"]
        )
        rows = self.log(**filters)
        count = 0
        for row in rows:
            writer.writerow(
                [
                    row.changed_at.isoformat(),
                    row.article.slug,
                    row.field,
                    row.old_value,
                    row.new_value,
                    row.actor.username,
                    row.reason,
                ]
            )
            count += 1
        AuditLog.objects.record(
            "kb_authority_log_exported",
            actor_type="human",
            actor_id=viewer.id,
            payload={
                "filters": {k: str(v) for k, v in filters.items() if v},
                "rows": count,
            },
        )
        return out.getvalue()


# --- the authority service ---

kb_authority = KbAuthority()
