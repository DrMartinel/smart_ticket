"""
Clarify-options tests (ADR-0023, ADR-0026). Jev scores each page a
clarifying question may offer; core-api builds the buttons from those
scores. A score must never be missing, partial or made up.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from ai_engine.graph.nodes.infer.proposals import (
    AutoReplyProposal,
    ClarificationProposal,
    LLMProposalEnvelope,
    RouteProposal,
)
from ai_engine.graph.nodes.score_options.node import score_options
from ai_engine.graph.state import RankedChunk


def _chunk(i: int, slug: str) -> RankedChunk:
    return RankedChunk(
        chunk_id=UUID(int=i),
        article_id=UUID(int=10 * i),
        article_slug=slug,
        content=f"c{i}",
        shortlist_score=0.5,
        rerank_score=0.9 if i == 1 else 0.05,
    )


_SHOWN = [_chunk(1, "portal"), _chunk(2, "root")]


def _clarify() -> LLMProposalEnvelope:
    return LLMProposalEnvelope(
        root=ClarificationProposal(
            proposed_intent="clarify",
            proposed_question="Which password?",
            proposed_options=["portal", "root"],
            rationale="names no system",
        )
    )


@pytest.fixture
def jev(fake_db, fake_option_scorer, use_db, use_option_scorer):
    """A fake Jev option scorer and the DB its passage titles come from."""

    def install(scores=None, error=None):
        use_db(fake_db())
        return use_option_scorer(fake_option_scorer(scores=scores, error=error))

    return install


# --- failure paths first ------------------------------------------------------


def test_a_jev_failure_while_scoring_options_propagates(jev, make_state):
    """Checks that a failed yes/no request fails the run (HITL as
    `ai_engine_unavailable`) instead of leaving the buttons unscored."""

    jev(error=RuntimeError("jev down"))

    with pytest.raises(RuntimeError, match="jev down"):
        score_options(
            make_state(proposal=_clarify(), reranked=_SHOWN, clarify_options_in_topk=True)
        )


def test_a_short_score_list_raises(jev, make_state):
    jev(scores=[0.9])

    with pytest.raises(ValueError, match="1 option scores for 2"):
        score_options(
            make_state(proposal=_clarify(), reranked=_SHOWN, clarify_options_in_topk=True)
        )


@pytest.mark.parametrize(
    "proposal, options_ok",
    [
        (None, False),
        (
            LLMProposalEnvelope(
                root=AutoReplyProposal(
                    proposed_intent="auto_reply",
                    kb_slug="portal",
                    verbatim_quote="a quote from the page",
                    answer_draft="a",
                    self_confidence=90,
                )
            ),
            False,
        ),
        (
            LLMProposalEnvelope(
                root=RouteProposal(
                    proposed_intent="route_to_team", rationale="r", self_confidence=90
                )
            ),
            False,
        ),
        (_clarify(), False),
    ],
    ids=["no proposal", "auto-reply", "route", "clarify with options not shown"],
)
def test_options_are_not_scored_unless_a_validated_clarify(jev, make_state, proposal, options_ok):
    """Checks that only a clarify whose options passed the validator costs
    Jev requests, and that every other run reports no scores."""

    fake = jev(scores=[0.9, 0.8])

    out = score_options(
        make_state(proposal=proposal, reranked=_SHOWN, clarify_options_in_topk=options_ok)
    )

    assert out == {"option_scores": []}
    assert fake.calls == []


# --- behaviour ------------------------------------------------------------------


def test_each_shown_page_is_scored_on_the_masked_ticket(jev, make_state):
    fake = jev(scores=[0.97, 0.79])
    state = make_state(proposal=_clarify(), reranked=_SHOWN, clarify_options_in_topk=True)

    out = score_options(state)

    assert out == {"option_scores": [0.97, 0.79]}
    [(subject, body, passages)] = fake.calls
    assert (subject, body) == (state.ticket.subject_masked, state.ticket.body_masked)
    assert [p.text for p in passages] == ["c1", "c2"]
