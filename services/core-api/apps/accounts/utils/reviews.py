"""Access reviews: a campaign over a set of grants, each answered by its reviewer (UC-F14-07)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import (
    AccessReviewCampaign,
    AccessReviewItem,
    Assignment,
    AssignmentSource,
    Department,
    NoAnswer,
    ReviewCampaignState,
    ReviewDecisionKind,
    User,
)
from apps.accounts.utils.access import Access
from apps.accounts.utils.catalog import Permission
from apps.accounts.utils.departments import departments
from apps.accounts.utils.grants import grants, live_role, require_reason
from apps.accounts.utils.vocabulary import EndReason, OrgError, OrgRefusal
from apps.audit.models import AuditLog
from apps.notifications.utils.notifier import Notice, notifier
from apps.notifications.utils.vocabulary import NotificationEvent


@dataclass(frozen=True)
class CampaignRequest:
    """Which grants a campaign covers, who answers when nobody else can, and when it closes."""

    name: str
    fallback_reviewer: str
    on_no_answer: NoAnswer
    role_urn: str | None = None
    department: str | None = None
    closes_at: datetime | None = None


class AccessReviews:
    """Opens, answers and closes access reviews."""

    def open(self, actor: User, request: CampaignRequest) -> AccessReviewCampaign:
        """A campaign with one item per manual grant in its filter, each sent to its reviewer."""
        name = require_reason(request.name)
        now = timezone.now()
        closes_at = request.closes_at or now + timedelta(
            days=settings.THRESHOLDS.access.review_default_days
        )
        if closes_at <= now:
            raise OrgError(422, OrgRefusal.ENDS_BEFORE_START, "a review closes in the future")
        fallback = User.objects.filter(username=request.fallback_reviewer, is_active=True).first()
        if fallback is None or not Access.of(fallback).holds(Permission.ACCESS_REVIEW_RESPOND):
            raise OrgError(
                422,
                OrgRefusal.FALLBACK_CANNOT_REVIEW,
                f"{request.fallback_reviewer!r} can't answer access reviews",
            )
        with transaction.atomic():
            role = live_role(request.role_urn) if request.role_urn else None
            department = departments.live(request.department) if request.department else None
            rows = self.in_scope(role, department)
            if not rows:
                raise OrgError(422, OrgRefusal.REVIEW_EMPTY, "no grant matches the review")
            campaign = AccessReviewCampaign.objects.create(
                name=name,
                role=role,
                department=department,
                on_no_answer=request.on_no_answer.value,
                fallback_reviewer=fallback,
                created_by=actor,
                closes_at=closes_at,
            )
            items = [
                AccessReviewItem(
                    campaign=campaign, assignment=row, reviewer=self.reviewer(row, fallback, actor)
                )
                for row in rows
            ]
            AccessReviewItem.objects.bulk_create(items)
            AuditLog.objects.record(
                "review_opened",
                actor_type="human",
                actor_id=actor.id,
                payload={"campaign": str(campaign.id), "name": name, "items": len(items)},
            )
            self.tell_reviewers(campaign, NotificationEvent.ACCESS_REVIEW_ASSIGNED)
        return campaign

    def in_scope(self, role: Any, department: Department | None) -> list[Assignment]:
        rows = (
            Assignment.objects.active()
            .exclude(source=AssignmentSource.STRUCTURAL.value)
            .filter(user__is_active=True)
            .select_related("user", "user__line_manager", "user__department", "role")
        )
        if role is not None:
            rows = rows.filter(role=role)
        if department is not None:
            rows = rows.filter(user__department_id__in=departments.subtree_ids(department))
        return list(rows)

    def reviewer(self, row: Assignment, fallback: User, opener: User) -> User:
        """The line manager, else the nearest department head, who can answer reviews; else the
        fallback; never the person whose grant it is (BR-F14-15)."""
        candidates: list[User | None] = [row.user.line_manager]
        department = row.user.department
        while department is not None:
            candidates.append(department.head)
            department = department.parent
        for candidate in [*candidates, fallback, opener]:
            if (
                candidate is not None
                and candidate.pk != row.user_id
                and candidate.is_active
                and Access.of(candidate).holds(Permission.ACCESS_REVIEW_RESPOND)
            ):
                return candidate
        return fallback

    def decide(
        self, actor: User, item_id: uuid.UUID, decision: ReviewDecisionKind, note: str
    ) -> AccessReviewItem:
        """The reviewer keeps or revokes one grant; a revoke ends it at once."""
        with transaction.atomic():
            item = (
                AccessReviewItem.objects.select_for_update()
                .select_related("campaign", "assignment", "assignment__user", "assignment__role")
                .filter(pk=item_id)
                .first()
            )
            if item is None:
                raise OrgError(404, OrgRefusal.REVIEW_NOT_FOUND, "no such review item")
            if item.reviewer_id != actor.pk or item.assignment.user_id == actor.pk:
                raise OrgError(
                    403, OrgRefusal.NOT_YOUR_REVIEW, "this grant is someone else's to review"
                )
            if item.campaign.state != ReviewCampaignState.OPEN.value:
                raise OrgError(409, OrgRefusal.REVIEW_CLOSED, "the review is closed")
            if item.decision:
                raise OrgError(409, OrgRefusal.REVIEW_DECIDED, "already answered")
            item.decision, item.note, item.decided_at = decision.value, note.strip(), timezone.now()
            item.save(update_fields=["decision", "note", "decided_at"])
            if decision is ReviewDecisionKind.REVOKE:
                grants.end_rows(
                    Assignment.objects.filter(pk=item.assignment_id),
                    EndReason.REVIEW_REVOKED,
                    actor,
                    note.strip() or "revoked in review",
                )
            else:
                Assignment.objects.filter(pk=item.assignment_id).update(
                    reviewed_at=item.decided_at, needs_review=False, review_due_at=None
                )
            AuditLog.objects.record(
                "review_decided",
                actor_type="human",
                actor_id=actor.id,
                payload={
                    "campaign": str(item.campaign_id),
                    "assignment": str(item.assignment_id),
                    "user": item.assignment.user.username,
                    "role": item.assignment.role.urn,
                    "decision": decision.value,
                    "note": note.strip(),
                },
            )
        return item

    def close(self, actor: User | None, campaign_id: uuid.UUID) -> AccessReviewCampaign:
        """Closes a campaign; each unanswered grant is revoked or flagged as the campaign says."""
        with transaction.atomic():
            campaign = (
                AccessReviewCampaign.objects.select_for_update().filter(pk=campaign_id).first()
            )
            if campaign is None:
                raise OrgError(404, OrgRefusal.REVIEW_NOT_FOUND, "no such review")
            if campaign.state != ReviewCampaignState.OPEN.value:
                raise OrgError(409, OrgRefusal.REVIEW_CLOSED, "the review is closed")
            unanswered = Assignment.objects.filter(
                pk__in=campaign.items.filter(decision="").values("assignment_id")
            )
            count = unanswered.count()
            if campaign.on_no_answer == NoAnswer.REVOKE.value:
                grants.end_rows(
                    unanswered, EndReason.REVIEW_NO_ANSWER, actor, f"unanswered in {campaign.name}"
                )
            else:
                unanswered.filter(ended_at__isnull=True).update(needs_review=True)
            campaign.state = ReviewCampaignState.CLOSED.value
            campaign.closed_at = timezone.now()
            campaign.save(update_fields=["state", "closed_at"])
            AuditLog.objects.record(
                "review_closed",
                actor_type="human" if actor else "system",
                actor_id=actor.id if actor else None,
                payload={
                    "campaign": str(campaign.id),
                    "unanswered": count,
                    "on_no_answer": campaign.on_no_answer,
                },
            )
        return campaign

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Closes campaigns past their date and reminds reviewers of ones closing soon."""
        now = now or timezone.now()
        due = AccessReviewCampaign.objects.filter(
            state=ReviewCampaignState.OPEN.value, closes_at__lte=now
        )
        closed = 0
        for campaign in due:
            self.close(None, campaign.id)
            closed += 1
        soon = AccessReviewCampaign.objects.filter(
            state=ReviewCampaignState.OPEN.value,
            reminded_at__isnull=True,
            closes_at__lte=now + timedelta(days=settings.THRESHOLDS.access.review_reminder_days),
        )
        reminded = 0
        for campaign in soon:
            self.tell_reviewers(campaign, NotificationEvent.ACCESS_REVIEW_CLOSING)
            AccessReviewCampaign.objects.filter(pk=campaign.pk).update(reminded_at=now)
            reminded += 1
        return {"closed": closed, "reminded": reminded}

    def tell_reviewers(self, campaign: AccessReviewCampaign, event: NotificationEvent) -> None:
        """One notice per reviewer with grants still to answer."""
        pending = (
            campaign.items.filter(decision="")
            .values("reviewer_id")
            .annotate(n=Count("id"))
            .order_by()
        )
        counts = {row["reviewer_id"]: row["n"] for row in pending}
        for reviewer in User.objects.filter(pk__in=counts):
            notifier.emit(
                event,
                None,
                Notice(
                    detail=campaign.name,
                    message=f"{counts[reviewer.pk]} grant(s) to review by "
                    f"{campaign.closes_at.date().isoformat()}",
                    link="/access/reviews",
                    subjects=(reviewer,),
                    data={"campaign": str(campaign.id), "pending": counts[reviewer.pk]},
                ),
            )

    def summary(self, campaign: AccessReviewCampaign) -> dict[str, int]:
        return campaign.items.aggregate(
            total=Count("id"),
            kept=Count("id", filter=Q(decision=ReviewDecisionKind.KEEP.value)),
            revoked=Count("id", filter=Q(decision=ReviewDecisionKind.REVOKE.value)),
            pending=Count("id", filter=Q(decision="")),
        )


# --- the access reviews service ---

access_reviews = AccessReviews()
