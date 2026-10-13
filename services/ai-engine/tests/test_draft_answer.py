"""
Checks DraftAnswerNode (ADR-0021): the draft it writes from the masked
ticket, and that every failure raises.
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
def run(use_draft_llm, use_embedder, fake_llm, fake_embedder, make_state):
    def go(reply=None, error=None, **state):
        llm = use_draft_llm(fake_llm(result=reply, error=error))
        embedder = use_embedder(fake_embedder(vector=[0.4]))
        return draft_answer(make_state(**state)), llm, embedder

    return go


def test_a_failed_chat_call_raises_rather_than_skipping_the_draft(run):
    with pytest.raises(AllLLMDownError):
        run(error=AllLLMDownError("chat down"))


@pytest.mark.parametrize("text", ['{"draft": "  "}', '{"other": "x"}', '["a list"]'])
def test_an_empty_or_misshapen_draft_raises(run, text):
    with pytest.raises(ValueError, match="empty"):
        run(reply=_reply(text))


def test_a_reply_that_is_not_json_raises(run):
    with pytest.raises(json.JSONDecodeError):
        run(reply=_reply("Amazon SES ... (plain text)"))


def test_the_draft_is_written_from_the_masked_ticket_only(run, make_ticket):
    ticket = make_ticket("Cannot send [EMAIL_1]", "Mail from [EMAIL_1] bounces")
    _, llm, _ = run(reply=_reply('{"draft": "SES bounces"}'), ticket=ticket)

    system, user = llm.prompts[0]
    assert system == DRAFT_PROMPT
    assert user == "Subject: Cannot send [EMAIL_1]\n\nMail from [EMAIL_1] bounces"


def test_the_draft_runs_at_the_configured_temperature(run):
    _, llm, _ = run(reply=_reply('{"draft": "SES bounces"}'))

    assert llm.temperatures == [settings.draft_temperature]


def test_the_draft_and_its_embedding_are_returned(run):
    out, _, embedder = run(reply=_reply('{"draft": " SES bounces "}'))

    assert out == {"draft_text": "SES bounces", "draft_embedding": [0.4]}
    assert embedder.calls == ["SES bounces"]


def test_the_draft_runs_on_its_own_model_never_the_proposals(
    use_draft_llm, use_llm, use_embedder, fake_llm, fake_embedder, make_state
):
    draft_model = use_draft_llm(fake_llm(result=_reply('{"draft": "SES bounces"}')))
    proposal_model = use_llm(fake_llm(error=AssertionError("the proposal's model was called")))
    use_embedder(fake_embedder(vector=[0.4]))

    draft_answer(make_state())

    assert len(draft_model.prompts) == 1
    assert proposal_model.prompts == []
