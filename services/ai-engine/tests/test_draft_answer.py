"""
DraftAnswerNode (HyDE, ADR-0021). The draft steers retrieval and nothing
else, so the failure that matters is the quiet one: a failed or empty draft
letting the ticket through on the weaker, ticket-only retrieval. These tests
pin that it raises instead, so the ticket reaches a person.
"""

from __future__ import annotations

import json

import pytest

from ai_engine.core.config import settings
from ai_engine.core.prompts import DRAFT_PROMPT
from ai_engine.core.providers.clients import AllLLMDownError, LLMResult
from ai_engine.graph.nodes.draft_answer.node import draft_answer


def _reply(text: str) -> LLMResult:
    return LLMResult(text=text, tokens_in=1, tokens_out=1, model="m", cost_usd=0.0)


@pytest.fixture
def run(use_llm, use_embedder, fake_llm, fake_embedder, make_state):
    def go(reply=None, error=None, **state):
        llm = use_llm(fake_llm(result=reply, error=error))
        embedder = use_embedder(fake_embedder(vector=[0.4]))
        return draft_answer(make_state(**state)), llm, embedder

    return go


def test_a_failed_chat_call_raises_rather_than_skipping_the_draft(run):
    """`AllLLMDownError` must propagate: the request fails, core-api sends
    the ticket to a person as ai_engine_unavailable. Catching it here would
    retrieve on the ticket alone with nothing recording the degrade."""

    with pytest.raises(AllLLMDownError):
        run(error=AllLLMDownError("chat down"))


@pytest.mark.parametrize("text", ['{"draft": "  "}', '{"other": "x"}', '["a list"]'])
def test_an_empty_or_misshapen_draft_raises(run, text):
    """A reply with no usable passage is a failure, not an empty search:
    BM25 and the embedder on "" would retrieve noise."""

    with pytest.raises(ValueError, match="empty"):
        run(reply=_reply(text))


def test_a_reply_that_is_not_json_raises(run):
    with pytest.raises(json.JSONDecodeError):
        run(reply=_reply("Amazon SES ... (plain text)"))


def test_the_draft_is_written_from_the_masked_ticket_only(run, make_ticket):
    """Only masked text may reach a model (spec §5); the draft call is a
    model call like any other."""

    ticket = make_ticket("Cannot send [EMAIL_1]", "Mail from [EMAIL_1] bounces")
    _, llm, _ = run(reply=_reply('{"draft": "SES bounces"}'), ticket=ticket)

    system, user = llm.prompts[0]
    assert system == DRAFT_PROMPT
    assert user == "Subject: Cannot send [EMAIL_1]\n\nMail from [EMAIL_1] bounces"


def test_the_draft_runs_at_the_configured_temperature(run):
    """At 0 the same ticket drafts, and so retrieves, the same way every run."""

    _, llm, _ = run(reply=_reply('{"draft": "SES bounces"}'))

    assert llm.temperatures == [settings.draft_temperature]


def test_the_draft_and_its_embedding_are_returned(run):
    out, _, embedder = run(reply=_reply('{"draft": " SES bounces "}'))

    assert out == {"draft_text": "SES bounces", "draft_embedding": [0.4]}
    assert embedder.calls == ["SES bounces"]
