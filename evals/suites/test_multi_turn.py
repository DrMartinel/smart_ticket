"""
Multi-turn chat follow-ups (F3, ADR-0034): each case carries the
conversation's earlier turns, sent to ai-engine as `prior_turns`, and the
decision is core-api's real `router.route()`, as in `test_end_to_end`.

Auto-reply precision on these cases has the same hard floor as the
single-turn set (spec §12.3, rule 9): a follow-up that says "I did that,
still failing" must never get the same page again. Only cases a reviewer
other than their author approved count; until there are some, the live
test skips and says so.

The structure checks run offline: every case is well formed, names pages
that exist, and expects `auto_reply` only from a page approved for it.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx
import pytest

from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.pipeline import router, trust_signals
from apps.tickets.utils.router import Branch
from infrastructure.dtos import EngineSignals, LLMProposalEnvelope

from suites.golden_utils import (
    DEMO_KB_MANIFEST,
    analyze,
    load_multi_turn,
    record_metric,
)
from suites.test_end_to_end import AUTO_REPLY_PRECISION_FLOOR, _kb_meta_for

KINDS = {"refers_back", "still_failing", "topic_switch", "more_detail"}
OUTCOMES = {"answered", "with_support", "clarify", "suggest_ticket"}
CURATION = DEMO_KB_MANIFEST.parent / "curation.json"


def _approved() -> set[str]:
    return {a["slug"] for a in json.loads(CURATION.read_text())["auto_reply"]}


def _pages() -> set[str]:
    return {p["slug"] for p in json.loads(DEMO_KB_MANIFEST.read_text())["pages"]}


def test_there_are_at_least_twenty_cases_of_every_kind():
    """F3 §g: at least 20 multi-turn cases."""
    cases = load_multi_turn()
    kinds = Counter(next(t for t in c["tags"] if t in KINDS) for c in cases)

    assert len(cases) >= 20
    assert set(kinds) == KINDS
    assert len({c["id"] for c in cases}) == len(cases)


def test_every_case_is_well_formed():
    pages, approved = _pages(), _approved()
    for case in load_multi_turn():
        assert case["prior_turns"], case["id"]
        for turn in case["prior_turns"]:
            assert turn["outcome"] in OUTCOMES, case["id"]
            assert (turn["outcome"] == "answered") == bool(turn["answer_excerpt"]), case["id"]
        truth = case["truth"]
        assert truth["expected_branch"] in {b.value for b in Branch}, case["id"]
        if truth["expected_branch"] == "auto_reply":
            assert truth["kb_slug"] in pages, case["id"]
            assert truth["kb_slug"] in approved, case["id"]
        assert case["review"]["status"] in {"pending", "approved", "rejected"}, case["id"]


def test_a_still_failing_case_never_expects_an_auto_reply():
    for case in load_multi_turn():
        if "still_failing" in case["tags"]:
            assert case["truth"]["expected_branch"] != "auto_reply", case["id"]


def test_multi_turn_auto_reply_precision(ai_engine_client, django_db_blocker):
    cases = load_multi_turn(reviewed_only=True)
    if not cases:
        pytest.skip("no multi-turn case has been approved by a reviewer yet (rule 9)")

    correct = predicted = right = 0
    misses: list[tuple[str, str, str]] = []
    for case in cases:
        try:
            result = analyze(
                ai_engine_client, case["subject"], case["body"], prior_turns=case["prior_turns"]
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise
            misses.append((case["id"], case["truth"]["expected_branch"], "<error>"))
            continue
        proposal_dict = result.get("proposal")
        proposal = LLMProposalEnvelope(root=proposal_dict) if proposal_dict else None
        with django_db_blocker.unblock():
            kb_meta = _kb_meta_for(proposal_dict)
        signals = trust_signals(
            EngineSignals(**result["signals"]),
            PIILevel(result["pii_level"]),
            kb_meta,
            clarifications_asked=0,
        )
        decision = router.route(signals, proposal, kb_meta)
        expected = case["truth"]["expected_branch"]
        if decision.branch.value == expected:
            correct += 1
        else:
            misses.append((case["id"], expected, decision.branch.value))
        if decision.branch is Branch.AUTO_REPLY:
            predicted += 1
            cited = proposal_dict.get("kb_slug") if proposal_dict else None
            right += expected == "auto_reply" and cited == case["truth"].get("kb_slug")

    accuracy = correct / len(cases)
    precision = right / predicted if predicted else None
    print(
        f"\nMulti-turn: branch_accuracy={accuracy} auto_reply_precision={precision} misses={misses}"
    )
    record_metric("multi_turn_branch_accuracy", accuracy, n=len(cases))
    if precision is not None:
        record_metric("multi_turn_auto_reply_precision", precision, n=predicted)
        assert precision >= AUTO_REPLY_PRECISION_FLOOR, (
            f"multi-turn auto-reply precision {precision:.2%} < {AUTO_REPLY_PRECISION_FLOOR:.0%}"
        )
