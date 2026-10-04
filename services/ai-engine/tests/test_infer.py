"""
Infer-node tests. A provider failure and unparseable output both reach
HITL, but the dashboard is built on the reason-code enum — so the
exact codes are part of the contract.
"""

from __future__ import annotations

from uuid import UUID

import json

import pytest

from ai_engine.core.providers.clients import AllLLMDownError, LLMResult
from ai_engine.graph.nodes.infer.proposals import LLMProposalEnvelope
from ai_engine.core.prompts import PROPOSE_PROMPT, load_system_prompt
from ai_engine.graph.nodes.infer.node import infer

_VALID_OUTPUT = json.dumps(
    {
        "proposed_intent": "route_to_team",
        "rationale": "người dùng không đăng nhập được",
        "self_confidence": 70.0,
    }
)


def _result(text: str = _VALID_OUTPUT, **kw) -> LLMResult:
    return LLMResult(
        text=text,
        tokens_in=kw.pop("tokens_in", 100),
        tokens_out=kw.pop("tokens_out", 20),
        model=kw.pop("model", "vllm/test"),
        cost_usd=kw.pop("cost_usd", 0.0),
        **kw,
    )


@pytest.fixture
def make_node(use_llm):
    def make(llm):
        use_llm(llm)
        return infer

    return make


def test_all_llm_down_maps_to_degraded_reason_all_llm_down(fake_llm, make_state, make_node):
    """Must not be confusable with "the model replied with bad JSON": both
    reach HITL, but only this one means the LLM itself failed."""

    out = make_node(fake_llm(error=AllLLMDownError("nothing answered")))(make_state())

    assert out["proposal"] is None
    assert out["degraded_reason"] == "all_llm_down"
    assert "tokens_in" not in out  # no call completed, so nothing is charged


def test_unparseable_output_yields_no_proposal_but_still_charges_tokens(
    fake_llm, make_state, make_node
):
    """Tokens burned on unparseable output still count toward
    cost_per_ticket, so a broken model is not free.
    """

    llm = fake_llm(result=_result(text="I'm afraid I can't do that."))

    out = make_node(llm)(make_state())

    assert out["proposal"] is None
    assert (out["tokens_in"], out["tokens_out"]) == (100, 20)


def test_schema_violating_json_yields_no_proposal(fake_llm, make_state, make_node):
    """Valid JSON that is not a valid proposal is still a schema failure —
    it must not slip through as a proposal with missing fields."""

    llm = fake_llm(result=_result(text=json.dumps({"proposed_intent": "nonsense"})))

    assert make_node(llm)(make_state())["proposal"] is None


def test_valid_output_is_parsed_into_a_proposal(fake_llm, make_state, make_node):
    out = make_node(fake_llm(result=_result()))(make_state())

    assert out["proposal"] is not None
    assert out["proposal"].root.proposed_intent == "route_to_team"
    assert out["model_used"] == "vllm/test"


def test_kb_slug_is_shown_to_the_model(fake_llm, make_state, make_candidate, make_node):
    """The model must echo kb_slug back in an AutoReplyProposal, so it has
    to be told what the slugs are — otherwise it invents one."""

    from ai_engine.graph.state import RankedChunk

    chunk = RankedChunk(
        chunk_id=UUID(int=1),
        article_id=UUID(int=10),
        article_slug="vpn-reset",
        content="nội dung",
        shortlist_score=0.9,
    )
    llm = fake_llm(result=_result())

    make_node(llm)(make_state(reranked=[chunk]))

    _, user_prompt = llm.prompts[0]
    assert "vpn-reset" in user_prompt


def test_the_system_prompt_is_the_propose_prompt(fake_llm, make_state, make_node):
    """The prompt `settings.prompt_version` selects is the one sent, so
    `ai_runs.prompt_version` names what actually ran."""

    llm = fake_llm(result=_result())

    make_node(llm)(make_state())

    [(system_prompt, _)] = llm.prompts
    assert system_prompt == PROPOSE_PROMPT


def test_the_reply_is_constrained_to_the_proposal_union(fake_llm, make_state, make_node):
    """The server decodes against the union's own schema, so a reply can't
    leave out a field or put a category in `proposed_intent`
    (evals/HISTORY.md 2026-10-04 (4))."""

    llm = fake_llm(result=_result())

    make_node(llm)(make_state())

    assert llm.schemas == [LLMProposalEnvelope.model_json_schema()]


def test_the_changelog_is_not_sent_to_the_model():
    """The prompt file's changelog is for people; sent, it took ~875 tokens
    of a 4096-token context on every classify call."""

    assert "<!--" not in PROPOSE_PROMPT
    assert "Changelog" not in PROPOSE_PROMPT
    assert PROPOSE_PROMPT.startswith("You are a triage assistant")


def test_an_unclosed_changelog_fails_the_boot(tmp_path, monkeypatch):
    """A prompt whose opening comment never closes would otherwise be sent
    whole, or cut at a random later "-->"; failing at import is the safe
    outcome."""

    from ai_engine.core import prompts

    (tmp_path / "broken.v1.md").write_text("<!-- changelog with no end\nYou are...")
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    with pytest.raises(ValueError, match="never closes"):
        prompts.load_system_prompt("broken.v1")


def test_invalid_prompt_version_is_rejected():
    """AIRunRequest.prompt_version is caller-supplied. If per-request prompt
    selection ever lands, a traversal must not read arbitrary files."""

    with pytest.raises(ValueError, match="invalid prompt version"):
        load_system_prompt("../../../etc/passwd")


def test_a_reply_that_still_carries_a_category_parses(make_state, fake_llm, use_llm):
    """A server that ignores the decoding schema, or an old few-shot, may
    still write `proposed_category`. It decides nothing (ADR-0017), so an
    extra key must not turn a good proposal into `schema_invalid`."""

    reply = json.dumps(
        {
            "proposed_intent": "route_to_team",
            "proposed_category": "access",
            "rationale": "r",
            "self_confidence": 70.0,
        }
    )
    use_llm(fake_llm(result=_result(reply)))

    out = infer(make_state())

    assert out["proposal"] is not None
    assert out["proposal"].root.proposed_intent == "route_to_team"


def test_the_decoding_schema_asks_for_no_category():
    """The schema vLLM decodes against: a category field in it would make the
    model spend tokens on an answer nobody reads."""
    schema = json.dumps(LLMProposalEnvelope.model_json_schema())

    assert "proposed_category" not in schema
    assert "proposed_subcategory" not in schema
