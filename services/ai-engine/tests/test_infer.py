"""
Infer-node tests. Circuit open, every provider down, and unparseable output
all reach HITL, but the dashboard is built on the reason-code enum — so the
exact codes are part of the contract.
"""

from __future__ import annotations

import json
import time

import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.llm.circuit_breaker import CircuitOpenError
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


def _node(llm, **kw):
    return InferNode(llm=llm, **kw)


def test_circuit_open_maps_to_degraded_reason_circuit_open(fake_llm, make_state):
    """Fail fast when the breaker is open, with the reason code verbatim."""

    out = _node(fake_llm(error=CircuitOpenError("open")))(make_state())

    assert out["proposal"] is None
    assert out["degraded_reason"] == "circuit_open"


def test_all_llm_down_maps_to_degraded_reason_all_llm_down(fake_llm, make_state):
    """Must not be confusable with "the model replied with bad JSON": both
    reach HITL, but only this one means the infrastructure is down."""

    out = _node(fake_llm(error=AllLLMDownError("nothing answered")))(make_state())

    assert out["proposal"] is None
    assert out["degraded_reason"] == "all_llm_down"
    assert "llm_calls" not in out  # no call was ever made, so nothing is charged


def test_budget_exhausted_makes_no_llm_call(fake_llm, exhausted_budget_state):
    llm = fake_llm(result=_result())

    out = _node(llm)(exhausted_budget_state())

    assert "proposal" not in out
    assert out["degraded_reason"] == "budget_exceeded"
    assert llm.prompts == []


def test_per_attempt_timeout_leaves_headroom_for_the_retry(fake_llm, make_state):
    """The client makes two attempts within the ticket's latency budget. Spending it all on the first attempt turns a
    recoverable blip into all_llm_down.
    """

    llm = fake_llm(result=_result())
    state = make_state(started_at=time.time(), max_latency_sec=60)

    _node(llm)(state)

    (timeout,) = llm.timeouts
    assert timeout <= 60 / 2 + 0.1
    assert timeout >= settings.min_attempt_timeout_sec


def test_per_attempt_timeout_is_clamped_by_the_model_ceiling(fake_llm, make_state, monkeypatch):
    """Whichever of the two budgets binds first wins: a generous per-ticket
    budget must not let a single call hang past the model ceiling."""

    monkeypatch.setattr(settings, "model_timeout_sec", 10.0)
    llm = fake_llm(result=_result())

    _node(llm)(make_state(max_latency_sec=3600))

    assert llm.timeouts == [10.0]


def test_per_attempt_timeout_never_drops_below_the_floor(fake_llm, make_state):
    """An almost-expired budget still gets a usable window — a sub-second
    timeout guarantees a failure that looks like a provider outage."""

    llm = fake_llm(result=_result())

    _node(llm)(make_state(started_at=time.time() - 590, max_latency_sec=600))

    assert llm.timeouts[0] >= settings.min_attempt_timeout_sec


def test_unparseable_output_yields_no_proposal_but_still_charges_tokens(fake_llm, make_state):
    """Tokens burned on unparseable output still count against the budget and
    cost_per_ticket, so a broken model cannot loop for free.
    """

    llm = fake_llm(result=_result(text="I'm afraid I can't do that."))

    out = _node(llm)(make_state())

    assert out["proposal"] is None
    assert out["tokens_used"] == 120
    assert out["llm_calls"] == 1


def test_schema_violating_json_yields_no_proposal(fake_llm, make_state):
    """Valid JSON that is not a valid proposal is still a schema failure —
    it must not slip through as a proposal with missing fields."""

    llm = fake_llm(result=_result(text=json.dumps({"proposed_intent": "nonsense"})))

    assert _node(llm)(make_state())["proposal"] is None


def test_valid_output_is_parsed_into_a_proposal(fake_llm, make_state):
    out = _node(fake_llm(result=_result()))(make_state())

    assert out["proposal"] is not None
    assert out["proposal"].root.proposed_intent == "route_to_team"
    assert out["model_used"] == "vllm/test"


def test_token_and_cost_counters_accumulate_across_the_retry(fake_llm, make_state):
    """The validate -> infer edge can run this node twice. Counters must add
    rather than overwrite, or a two-attempt ticket reports half its cost."""

    llm = fake_llm(result=_result(tokens_in=10, tokens_out=5, cost_usd=0.5))

    out = _node(llm)(
        make_state(tokens_used=100, llm_calls=1, tokens_in=10, tokens_out=5, cost_usd=0.5)
    )

    assert out["tokens_used"] == 115
    assert out["llm_calls"] == 2
    assert out["cost_usd"] == 1.0


def test_kb_slug_is_shown_to_the_model(fake_llm, make_state, make_candidate):
    """The model must echo kb_slug back in an AutoReplyProposal, so it has
    to be told what the slugs are — otherwise it invents one."""

    from ai_engine.core.state import RankedChunk

    chunk = RankedChunk(
        chunk_id=1, article_id=10, article_slug="vpn-reset", content="nội dung", score=0.9
    )
    llm = fake_llm(result=_result())

    _node(llm)(make_state(reranked=[chunk]))

    _, user_prompt = llm.prompts[0]
    assert "vpn-reset" in user_prompt


def test_invalid_prompt_version_is_rejected():
    """AIRunRequest.prompt_version is caller-supplied. If per-request prompt
    selection ever lands, a traversal must not read arbitrary files."""

    with pytest.raises(ValueError, match="invalid prompt version"):
        load_system_prompt("../../../etc/passwd")
