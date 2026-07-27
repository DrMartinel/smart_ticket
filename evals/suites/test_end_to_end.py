"""
End-to-end — spec §12.2 (`test_end_to_end`, branch accuracy + auto-reply
precision). This is the one suite that exercises the REAL decision path:
live ai-engine for signals/proposal, then core-api's actual
`router.route()` — the identical function used in production, imported
directly rather than reimplemented here — with a real `KBArticleMeta`
looked up from the database exactly as `apps/tickets/tasks.py` does.

Auto-reply precision is checked against spec §12.3's absolute (not
relative-to-baseline) gate: >= 0.95, no exceptions, because a false
auto-reply is the single most expensive failure mode in this system
(spec §11.1: "auto-reply sai nhưng ticket đã đóng = thất bại vô hình").

Branch accuracy is REPORTED, not hard-gated: spec §12.3's actual CI gate
list only names `auto_reply_precision` as a hard threshold for this
suite — and correctly so pre-calibration. `trust_model_v0.json` is an
explicitly uncalibrated placeholder (see that file's own "note" field)
and this golden set is synthetic; a system with an unfit trust model
routing more conservatively to HITL is exactly correct behavior at this
stage, not a bug — see spec §14 P1→P2: real branch-accuracy improvement
is what shadow-mode calibration is FOR, not something a fixed
pre-calibration threshold should gate.
"""

from __future__ import annotations

from contracts.enums import Branch
from contracts.routing import KBArticleMeta
from contracts.trust import TrustSignals
from django.conf import settings

from apps.kb.models import KbArticle
from apps.tickets.services.router import route
from suites.golden_utils import analyze, load_golden, record_metric, sample

AUTO_REPLY_PRECISION_FLOOR = 0.95  # spec §12.3 — hard threshold, not relative


def _kb_meta_for(proposal: dict | None) -> KBArticleMeta | None:
    if not proposal or proposal.get("proposed_intent") != "auto_reply":
        return None
    kb = KbArticle.objects.filter(slug=proposal.get("kb_slug"), is_active=True).first()
    if kb is None:
        return None
    return KBArticleMeta(
        id=kb.id, slug=kb.slug, category=kb.category, auto_reply_allowed=kb.auto_reply_allowed, risk_tier=kb.risk_tier
    )


def test_branch_accuracy_and_auto_reply_precision(ai_engine_client, django_db_blocker):
    # pytest-django installs a global guard that blocks ANY Django DB
    # access unless explicitly allowed — it fires regardless of whether a
    # test requests the `db` fixture, whenever pytest-django is merely
    # installed (it is, as a core-api dependency). We don't want the `db`
    # fixture itself: that provisions and migrates a separate
    # pytest-django-managed test database, wrapped in a rolled-back
    # transaction. This suite wants the REAL, already-seeded dev database
    # — `django_db_blocker.unblock()` is pytest-django's documented escape
    # hatch for exactly that: raw DB access outside its test-DB machinery.
    cases = sample(load_golden(), n=15)
    correct = 0
    auto_reply_predicted = 0
    auto_reply_correct = 0
    mismatches = []

    for case in cases:
        result = analyze(ai_engine_client, case["subject"], case["body"], retrieval_floor=settings.THRESHOLDS.retrieval_floor)
        signals = TrustSignals(**result["signals"])
        proposal_dict = result.get("proposal")

        proposal = None
        if proposal_dict is not None:
            from contracts.llm_draft import LLMProposalEnvelope

            proposal = LLMProposalEnvelope(root=proposal_dict)

        with django_db_blocker.unblock():
            kb_meta = _kb_meta_for(proposal_dict)
        decision = route(signals, proposal, kb_meta, settings.THRESHOLDS)

        expected_branch = case["truth"].get("expected_branch")
        if expected_branch is not None:
            if decision.branch.value == expected_branch:
                correct += 1
            else:
                mismatches.append((case["id"], expected_branch, decision.branch.value, decision.reason_code.value))

        if decision.branch is Branch.AUTO_REPLY:
            auto_reply_predicted += 1
            if expected_branch == "auto_reply":
                auto_reply_correct += 1

    labeled = [c for c in cases if c["truth"].get("expected_branch") is not None]
    accuracy = correct / len(labeled) if labeled else None
    precision = auto_reply_correct / auto_reply_predicted if auto_reply_predicted else None

    # Reported, not gated — see module docstring for why a fixed
    # pre-calibration branch-accuracy threshold would be the wrong check.
    print(f"\nEnd-to-end: branch_accuracy={accuracy} auto_reply_precision={precision} " f"n={len(cases)} mismatches={mismatches}")

    if accuracy is not None:
        record_metric("branch_accuracy", accuracy, n=len(labeled))
    if precision is not None:
        record_metric("auto_reply_precision", precision, n=auto_reply_predicted)

    if precision is not None:
        assert precision >= AUTO_REPLY_PRECISION_FLOOR, (
            f"auto-reply precision {precision:.2%} < hard floor {AUTO_REPLY_PRECISION_FLOOR:.0%} "
            f"({auto_reply_correct}/{auto_reply_predicted})"
        )
