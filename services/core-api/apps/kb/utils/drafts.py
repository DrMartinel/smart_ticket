"""KB drafts (F6, ADR-0036): written by a KB editor, approved by a second person, then published
into `kb_articles`. Publishing never grants auto-reply authority; a changed text or a retirement
revokes it."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Capability, User
from apps.audit.models import AuditLog
from apps.core.errors import CodedError
from apps.kb.models import (
    DraftKind,
    DraftState,
    GapState,
    KbArticle,
    KbAuthorityLog,
    KbDraft,
    KbGapCluster,
)
from apps.kb.utils.chunking import chunk_sections
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent
from apps.tickets.utils.router import RiskTier


class KbRefusal(StrEnum):
    NOT_ALLOWED = "not_allowed"
    ARTICLE_NOT_FOUND = "article_not_found"
    DRAFT_NOT_FOUND = "draft_not_found"
    SLUG_TAKEN = "slug_taken"
    NOT_EDITABLE = "not_editable"
    NOT_IN_REVIEW = "not_in_review"
    SELF_REVIEW = "self_review"
    COMMENT_REQUIRED = "comment_required"
    CONFLICT = "conflict"
    EMPTY = "title_and_body_required"
    HIGH_RISK_BULK = "high_risk_needs_single_review"
    REASON_REQUIRED = "reason_required"
    CLUSTER_NOT_FOUND = "cluster_not_found"


class KbError(CodedError):
    """A KB governance request core-api refuses."""


class AuthorityReason(StrEnum):
    NEW = "new"
    REGRANT = "regrant"
    TIER = "tier"


@dataclass
class DraftDiff:
    title_diff: list[str]
    body_diff: list[str]
    chunks_preview: list[dict[str, Any]]


def can_edit_kb(user: User) -> bool:
    """KB editors and managers write and review drafts."""
    return user.is_manager or Capability.KB_EDITOR.value in user.capability_set()


class KbDrafts:
    """Drafts from creation to publication."""

    def check_editor(self, actor: User) -> None:
        if not can_edit_kb(actor):
            raise KbError(403, KbRefusal.NOT_ALLOWED, "KB editors and managers only")

    def get(self, draft_id: Any, *, lock: bool = False) -> KbDraft:
        rows = KbDraft.objects.select_related("article", "author", "reviewer")
        if lock:
            rows = rows.select_for_update(of=("self",))
        draft = rows.filter(pk=draft_id).first()
        if draft is None:
            raise KbError(404, KbRefusal.DRAFT_NOT_FOUND, "no such draft")
        return draft

    # ── writing (UC-F6-01) ──

    def create(self, actor: User, data: dict[str, Any]) -> KbDraft:
        """A draft for a new page, an edit or a retirement of a live one."""
        self.check_editor(actor)
        kind = DraftKind(data["kind"])
        slug = data["slug"].strip()
        article = KbArticle.objects.filter(slug=slug).first()
        if kind is DraftKind.CREATE and article is not None:
            raise KbError(409, KbRefusal.SLUG_TAKEN, f"{slug} exists: draft an edit")
        if kind is not DraftKind.CREATE and (article is None or not article.is_active):
            raise KbError(404, KbRefusal.ARTICLE_NOT_FOUND, f"no live page {slug}")
        title = (data.get("title") or (article.title if article else "")).strip()
        body = data.get("body") or (article.body if article else "")
        if not title or not body.strip():
            raise KbError(422, KbRefusal.EMPTY, "write a title and a body")
        cluster = None
        if data.get("gap_cluster_id"):
            cluster = KbGapCluster.objects.filter(pk=data["gap_cluster_id"]).first()
            if cluster is None:
                raise KbError(404, KbRefusal.CLUSTER_NOT_FOUND, "no such gap cluster")
        with transaction.atomic():
            draft = KbDraft.objects.create(
                kind=kind.value,
                article=article,
                slug=slug,
                title=title,
                body=body,
                category=data.get("category") or (article.category if article else "other"),
                proposed_risk_tier=data.get("proposed_risk_tier")
                or (article.risk_tier if article else RiskTier.HIGH.value),
                change_note=data.get("change_note", ""),
                base_version=article.version if article else None,
                base_text_sha256=article.text_sha256() if article else "",
                author=actor,
                gap_cluster=cluster,
            )
            if cluster is not None:
                KbGapCluster.objects.filter(pk=cluster.pk).update(state=GapState.DRAFTED.value)
            self.audit("kb_draft_created", actor, draft)
        return draft

    def update(self, draft_id: Any, actor: User, fields: dict[str, Any]) -> KbDraft:
        with transaction.atomic():
            draft = self.get(draft_id, lock=True)
            if draft.author_id != actor.id:
                raise KbError(403, KbRefusal.NOT_ALLOWED, "only the author edits a draft")
            if not draft.is_editable():
                raise KbError(409, KbRefusal.NOT_EDITABLE, f"the draft is {draft.state}")
            for name in ("title", "body", "category", "proposed_risk_tier", "change_note"):
                if fields.get(name) is not None:
                    setattr(draft, name, fields[name])
            if not draft.title.strip() or not draft.body.strip():
                raise KbError(422, KbRefusal.EMPTY, "write a title and a body")
            draft.save()
        return draft

    def submit(self, draft_id: Any, actor: User) -> KbDraft:
        """Sends the draft for review; KB editors and managers are told."""
        with transaction.atomic():
            draft = self.get(draft_id, lock=True)
            if draft.author_id != actor.id:
                raise KbError(403, KbRefusal.NOT_ALLOWED, "only the author submits a draft")
            if not draft.is_editable():
                raise KbError(409, KbRefusal.NOT_EDITABLE, f"the draft is {draft.state}")
            draft.state = DraftState.IN_REVIEW.value
            draft.save(update_fields=["state", "updated_at"])
            self.audit("kb_draft_submitted", actor, draft)
            notifier.emit(
                NotificationEvent.KB_REVIEW_REQUESTED,
                notice=Notice(
                    actor=actor.username,
                    reason=draft.slug,
                    message=draft.title,
                    detail=draft.change_note or draft.kind,
                    link=f"/kb/drafts/{draft.id}",
                    data={"draft": str(draft.id), "kind": draft.kind},
                ),
            )
        return draft

    def withdraw(self, draft_id: Any, actor: User) -> KbDraft:
        with transaction.atomic():
            draft = self.get(draft_id, lock=True)
            if draft.author_id != actor.id and not actor.is_manager:
                raise KbError(403, KbRefusal.NOT_ALLOWED, "the author or a manager")
            if not draft.is_editable() and draft.state != DraftState.CONFLICT.value:
                raise KbError(409, KbRefusal.NOT_EDITABLE, f"the draft is {draft.state}")
            draft.state = DraftState.WITHDRAWN.value
            draft.save(update_fields=["state", "updated_at"])
        return draft

    def rebase(self, draft_id: Any, actor: User) -> KbDraft:
        """A conflicting draft starts again from the live page's current text, keeping its own."""
        with transaction.atomic():
            draft = self.get(draft_id, lock=True)
            if draft.author_id != actor.id:
                raise KbError(403, KbRefusal.NOT_ALLOWED, "only the author rebases a draft")
            if draft.state != DraftState.CONFLICT.value or draft.article is None:
                raise KbError(409, KbRefusal.NOT_EDITABLE, f"the draft is {draft.state}")
            draft.base_version = draft.article.version
            draft.base_text_sha256 = draft.article.text_sha256()
            draft.state = DraftState.DRAFT.value
            draft.save()
        return draft

    def diff(self, draft: KbDraft) -> DraftDiff:
        """The draft against the live page, and how the ingest chunker splits its body."""
        if draft.state == DraftState.PUBLISHED.value:
            old_title, old_body = draft.previous_title, draft.previous_body
        else:
            old_title = draft.article.title if draft.article else ""
            old_body = draft.article.body if draft.article else ""
        return DraftDiff(
            title_diff=list(difflib.unified_diff([old_title], [draft.title], lineterm="", n=0)),
            body_diff=list(
                difflib.unified_diff(
                    old_body.splitlines(), draft.body.splitlines(), lineterm="", n=2
                )
            ),
            chunks_preview=[
                {"section_title": c.section_title, "content": c.content}
                for c in chunk_sections(draft.body)
            ],
        )

    # ── review and publication (UC-F6-02, 03, 07) ──

    def review(self, draft_id: Any, actor: User, approve: bool, comment: str) -> KbDraft:
        """Approve publishes; request changes sends it back with the comment. Never the author."""
        self.check_editor(actor)
        with transaction.atomic():
            draft = self.get(draft_id, lock=True)
            if draft.author_id == actor.id:
                raise KbError(403, KbRefusal.SELF_REVIEW, "a second person reviews a draft")
            if draft.state != DraftState.IN_REVIEW.value:
                raise KbError(409, KbRefusal.NOT_IN_REVIEW, f"the draft is {draft.state}")
            draft.reviewer, draft.review_comment = actor, comment.strip()
            if not approve:
                if not comment.strip():
                    raise KbError(422, KbRefusal.COMMENT_REQUIRED, "say what to change")
                draft.state = DraftState.CHANGES_REQUESTED.value
                draft.save()
                self.audit("kb_draft_reviewed", actor, draft, decision="request_changes")
                return draft
            if draft.article is not None:
                article = KbArticle.objects.select_for_update().get(pk=draft.article.pk)
                if article.text_sha256() != draft.base_text_sha256 or not article.is_active:
                    draft.state = DraftState.CONFLICT.value
                    draft.save()
                    self.audit("kb_draft_reviewed", actor, draft, decision="conflict")
                    return draft
            self.audit("kb_draft_reviewed", actor, draft, decision="approve")
            self.publish(draft, actor)
        return draft

    def publish(self, draft: KbDraft, actor: User) -> KbArticle:
        """Writes the draft into `kb_articles` with no authority, revoking any the old text had,
        and queues the ingest."""
        from apps.kb.tasks import publish_draft

        kind = DraftKind(draft.kind)
        if kind is DraftKind.CREATE:
            article = KbArticle.objects.create(
                slug=draft.slug,
                title=draft.title,
                body=draft.body,
                category=draft.category,
                risk_tier=RiskTier.HIGH.value,
            )
            draft.article = article
            pending = AuthorityReason.NEW
        else:
            assert draft.article is not None
            article = KbArticle.objects.select_for_update().get(pk=draft.article.pk)
            draft.previous_title, draft.previous_body = article.title, article.body
            changed = (article.title, article.body) != (draft.title, draft.body)
            if kind is DraftKind.RETIRE:
                article.is_active = False
                self.revoke(article, actor, f"Trang bị gỡ ở bản nháp {draft.id}")
                pending = None
            else:
                had_authority = article.auto_reply_allowed
                if changed:
                    self.revoke(
                        article,
                        actor,
                        f"Nội dung thay đổi ở bản nháp {draft.id}; cần phê duyệt lại",
                    )
                article.title, article.body, article.category = (
                    draft.title,
                    draft.body,
                    draft.category,
                )
                article.version += 1
                if changed and had_authority:
                    pending = AuthorityReason.REGRANT
                elif draft.proposed_risk_tier != article.risk_tier:
                    pending = AuthorityReason.TIER
                else:
                    pending = None
            article.save()
        draft.state = DraftState.PUBLISHED.value
        draft.published_at = timezone.now()
        draft.authority_pending = pending is not None
        draft.authority_reason = pending.value if pending else ""
        draft.save()
        AuditLog.objects.record(
            "kb_retired" if kind is DraftKind.RETIRE else "kb_published",
            actor_type="human",
            actor_id=actor.id,
            payload={
                "slug": article.slug,
                "draft": str(draft.id),
                "kind": kind.value,
                "version": article.version,
            },
        )
        if pending is not None:
            notifier.emit(
                NotificationEvent.KB_AUTHORITY_NEEDED,
                notice=Notice(
                    actor=actor.username,
                    reason=article.slug,
                    message=article.title,
                    detail=pending.value,
                    link="/kb/authority",
                    data={"slug": article.slug, "reason": pending.value},
                ),
            )
        if kind is not DraftKind.RETIRE:
            draft_id = str(draft.id)
            transaction.on_commit(lambda: publish_draft.delay(draft_id))
        return article

    def ingest(self, draft_id: Any) -> int:
        """Chunks and embeds a published draft's page; on failure the old chunks stay and the
        failure is audited."""
        from apps.kb.utils.indexing import indexer

        draft = KbDraft.objects.select_related("article").filter(pk=draft_id).first()
        if draft is None or draft.state != DraftState.PUBLISHED.value or draft.article is None:
            return 0
        if not draft.article.is_active:
            return 0
        try:
            with transaction.atomic():
                return len(indexer.ingest(draft.article))
        except Exception as e:
            AuditLog.objects.record(
                "kb_ingest_failed",
                actor_type="system",
                payload={"slug": draft.article.slug, "draft": str(draft.id), "error": str(e)},
            )
            return 0

    def revoke(self, article: KbArticle, actor: User, reason: str) -> None:
        """Takes away auto-reply authority with a log row; any publisher may (BR-F6-04)."""
        if not article.auto_reply_allowed:
            return
        article.auto_reply_allowed = False
        KbAuthorityLog.objects.create(
            article=article,
            field="auto_reply_allowed",
            old_value="True",
            new_value="False",
            actor=actor,
            reason=reason,
        )
        AuditLog.objects.record(
            "kb_authority_revoked",
            actor_type="human",
            actor_id=actor.id,
            payload={"slug": article.slug, "reason": reason},
        )

    def audit(self, event: str, actor: User, draft: KbDraft, **extra: Any) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human",
            actor_id=actor.id,
            payload={"draft": str(draft.id), "slug": draft.slug, "kind": draft.kind, **extra},
        )


# --- the drafts service ---

kb_drafts = KbDrafts()
