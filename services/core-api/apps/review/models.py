"""HITL queue + eval data — spec §3.4."""

from __future__ import annotations


from enum import StrEnum

from django.conf import settings
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.models import BaseModel
from apps.tickets.utils.router import ReviewQueue
from apps.accounts.models import User
from apps.kb.models import KbArticle
from apps.tickets.models import AiRun, Ticket


class ReviewAction(StrEnum):
    APPROVE = "approve"
    EDIT_AND_SEND = "edit_and_send"
    REJECT = "reject"
    REROUTE = "reroute"
    ESCALATE = "escalate"


class Verdict(StrEnum):
    CORRECT = "correct"
    WRONG = "wrong"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"


class ReviewError(Exception):
    pass


# Queues of blocked tickets: their content is the attack or the secret (F8, BR-F8-07).
SECURITY_QUEUES = frozenset({"injection", "pii_verify"})


class ReviewItemManager(models.Manager["ReviewItem"]):
    def for_queue(
        self, *, queue: str | None, state: str, security: bool = False
    ) -> QuerySet[ReviewItem]:
        """The HITL queue (spec §3.4): most urgent first (priority 1 = blocked,
        escalated or mask-failed), then longest-waiting first within a
        priority. The blocked tickets' queues only for `security` (BR-F8-07)."""
        qs = self.select_related("ticket", "ai_run", "comment").filter(state=state)
        if not security:
            qs = qs.exclude(queue__in=SECURITY_QUEUES)
        if queue:
            qs = qs.filter(queue=queue)
        return qs.order_by("priority", "created_at")


class ReviewItem(BaseModel):
    OPEN_STATES = ("pending", "claimed")

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="review_items")
    ai_run = models.ForeignKey(
        AiRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    queue = models.CharField(max_length=30, choices=[(q.value, q.value) for q in ReviewQueue])
    # A comment whose masking failed (F3 UC-F3-03 3y); None for a ticket's routing review.
    comment = models.ForeignKey(
        "tickets.TicketComment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="review_items",
    )
    priority = models.SmallIntegerField(default=3)
    state = models.CharField(max_length=20, default="pending")
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "review_items"

    objects = ReviewItemManager()

    @property
    def is_open(self) -> bool:
        """Whether the item still waits for a person."""
        return self.state in self.OPEN_STATES

    @transaction.atomic
    def claim(self, actor: User) -> ReviewItem:
        if self.state != "pending":
            raise ReviewError(f"review item {self.id} is not pending (state={self.state})")
        self.state = "claimed"
        self.claimed_by = actor
        self.claimed_at = timezone.now()
        self.save(update_fields=["state", "claimed_by", "claimed_at"])
        return self


class ReviewDecision(BaseModel):
    """One human decision = one training label. Spec §3.4: "câu hỏi cụ
    thể, không phải nút Approve" — this is why the fields below are
    specific verdicts, not a single approve/reject boolean."""

    review_item = models.ForeignKey(ReviewItem, on_delete=models.CASCADE, related_name="decisions")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

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

    class Meta(BaseModel.Meta):
        db_table = "review_decisions"


class EvalCandidate(BaseModel):
    """Auto-generated golden-set candidate from any human override — spec
    §12.4's free-label loop."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="eval_candidates")
    source = models.CharField(
        max_length=30
    )  # human_override|reroute|reopen|low_rating|refusal_spike
    ai_prediction = models.JSONField()
    human_truth = models.JSONField()
    promoted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        db_table = "eval_candidates"
