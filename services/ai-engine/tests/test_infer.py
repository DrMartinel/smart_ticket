"""
Infer-node tests. A provider failure and unparseable output both reach
HITL, but the dashboard is built on the reason-code enum — so the
exact codes are part of the contract.
"""

from __future__ import annotations

import json

import pytest

from ai_engine.core.providers.llm.models import AllLLMDownError, LLMResult
from ai_engine.core.prompts import load_system_prompt
from ai_engine.graph.nodes.infer import InferNode

_VALID_OUTPUT = json.dumps(
    {
        "proposed_intent": "route_to_team",
        "proposed_category": "access",
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
        return InferNode()

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

    from ai_engine.core.state import RankedChunk

    chunk = RankedChunk(
        chunk_id=1, article_id=10, article_slug="vpn-reset", content="nội dung", score=0.9
    )
    llm = fake_llm(result=_result())

    make_node(llm)(make_state(reranked=[chunk]))

    _, user_prompt = llm.prompts[0]
    assert "vpn-reset" in user_prompt


def test_invalid_prompt_version_is_rejected():
    """AIRunRequest.prompt_version is caller-supplied. If per-request prompt
    selection ever lands, a traversal must not read arbitrary files."""

    with pytest.raises(ValueError, match="invalid prompt version"):
        load_system_prompt("../../../etc/passwd")
