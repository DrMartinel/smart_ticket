"""HITL queue + eval data — spec §3.4."""

from django.conf import settings
from django.db import models

from contracts.enums import ReviewAction, ReviewQueue, Verdict
from apps.kb.models import KbArticle
from apps.tickets.models import AiRun, Ticket


class ReviewItem(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="review_items")
    ai_run = models.ForeignKey(
        AiRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    queue = models.CharField(max_length=30, choices=[(q.value, q.value) for q in ReviewQueue])
    priority = models.SmallIntegerField(default=3)
    state = models.CharField(max_length=20, default="pending")
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_items"


class ReviewDecision(models.Model):
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

    class Meta:
        db_table = "review_decisions"


class EvalCandidate(models.Model):
    """Auto-generated golden-set candidate from any human override — spec
    §12.4's free-label loop."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="eval_candidates")
    source = models.CharField(max_length=30)  # human_override|reroute|reopen|refusal_spike
    ai_prediction = models.JSONField()
    human_truth = models.JSONField()
    promoted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "eval_candidates"
