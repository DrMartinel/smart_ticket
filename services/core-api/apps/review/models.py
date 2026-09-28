"""HITL queue + eval data — spec §3.4."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone

from contracts.enums import ReviewAction, ReviewQueue, Verdict
from apps.accounts.models import User
from apps.kb.models import KbArticle
from apps.tickets.models import AiRun, Ticket

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager


class ReviewError(Exception):
    pass


class ReviewItemManager(models.Manager["ReviewItem"]):
    def for_queue(self, *, queue: str | None, state: str) -> QuerySet[ReviewItem]:
        """The HITL queue (spec §3.4): most urgent first (priority 1 = blocked,
        escalated or mask-failed), then longest-waiting first within a
        priority."""
        qs = self.select_related("ticket", "ai_run").filter(state=state)
        if queue:
            qs = qs.filter(queue=queue)
        return qs.order_by("priority", "created_at")


class ReviewItem(models.Model):
    id: int
    ticket_id: int
    ai_run_id: int | None
    claimed_by_id: int | None
    decisions: RelatedManager[ReviewDecision]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="review_items")
    ai_run = models.ForeignKey(
        AiRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    queue = models.CharField(max_length=30, choices=[(q.value, q.value) for q in ReviewQueue])
    priority = models.SmallIntegerField(default=3)
    state = models.CharField(max_length=20, default="pending")
    claimed_by = models.ForeignKey[User](
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_items"

    # django-types types Model.objects as BaseManager[Model], so any custom manager
    # reads as an incompatible override.
    objects: ClassVar[ReviewItemManager] = ReviewItemManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    @transaction.atomic
    def claim(self, actor: User) -> ReviewItem:
        if self.state != "pending":
            raise ReviewError(f"review item {self.id} is not pending (state={self.state})")
        self.state = "claimed"
        self.claimed_by = actor
        self.claimed_at = timezone.now()
        self.save(update_fields=["state", "claimed_by", "claimed_at"])
        return self

    @transaction.atomic
    def decide(
        self,
        reviewer: User,
        *,
        action_taken: str,
        kb_verdict: str | None,
        category_verdict: str | None,
        corrected_category: str | None,
        corrected_kb_id: int | None,
        override_reason: str | None,
        time_spent_sec: int,
    ) -> ReviewDecision:
        """Records the decision and resolves the item. This is where the
        free-label loop (spec §12.4) actually gets created: any action other
        than a clean "approve" becomes an `EvalCandidate`, carrying the
        human's correction and — crucially — their stated reason, without
        which the override is data but not a teachable case."""
        if action_taken != "approve" and not (override_reason and override_reason.strip()):
            raise ReviewError("override_reason is required when action_taken != 'approve'")

        decision = ReviewDecision.objects.create(
            review_item=self,
            reviewer=reviewer,
            kb_verdict=kb_verdict,
            category_verdict=category_verdict,
            corrected_category=corrected_category,
            corrected_kb_id=corrected_kb_id,
            action_taken=action_taken,
            override_reason=override_reason,
            time_spent_sec=time_spent_sec,
        )

        self.state = "resolved"
        self.save(update_fields=["state"])

        if action_taken != "approve":
            ai_run = self.ai_run
            ai_prediction = (ai_run.proposed_draft or {}) if ai_run is not None else {}
            EvalCandidate.objects.create(
                ticket=self.ticket,
                source="human_override",
                ai_prediction=ai_prediction,
                human_truth={
                    "action_taken": action_taken,
                    "kb_verdict": kb_verdict,
                    "category_verdict": category_verdict,
                    "corrected_category": corrected_category,
                    "corrected_kb_id": corrected_kb_id,
                    "override_reason": override_reason,
                },
            )

        return decision


class ReviewDecision(models.Model):
    """One human decision = one training label. Spec §3.4: "câu hỏi cụ
    thể, không phải nút Approve" — this is why the fields below are
    specific verdicts, not a single approve/reject boolean."""

    id: int
    review_item_id: int
    reviewer_id: int
    corrected_kb_id: int | None

    review_item = models.ForeignKey(ReviewItem, on_delete=models.CASCADE, related_name="decisions")
    reviewer = models.ForeignKey[User](settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    kb_verdict = models.CharField(
        max_length=20, choices=[(v.value, v.value) for v in Verdict], null=True, blank=True
    )
    category_verdict = models.CharField(max_length=20, null=True, blank=True)  # correct|wrong
    corrected_category = models.CharField(max_length=20, null=True, blank=True)
    corrected_kb = models.ForeignKey(
        KbArticle, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action_taken = models.CharField(
        max_length=20, choices=[(a.value, a.value) for a in ReviewAction]
    )
    override_reason = models.TextField(null=True, blank=True)  # REQUIRED when action != approve

    time_spent_sec = models.IntegerField()  # detects approval fatigue
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_decisions"


class EvalCandidate(models.Model):
    """Auto-generated golden-set candidate from any human override — spec
    §12.4's free-label loop."""

    id: int
    ticket_id: int

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="eval_candidates")
    source = models.CharField(max_length=30)  # human_override|reroute|reopen|refusal_spike
    ai_prediction: models.JSONField[dict[str, Any]] = models.JSONField()
    human_truth: models.JSONField[dict[str, Any]] = models.JSONField()
    promoted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "eval_candidates"
