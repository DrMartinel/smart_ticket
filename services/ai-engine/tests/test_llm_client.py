"""
LLM-client tests: where an unusable provider reply ends up.

Blank, non-string or missing content must be treated like a transport failure
— retry, fall back, then AllLLMDownError → HITL. Escaping the client would be
a 500 with no TrustSignals. Drives a fake `LLMClient` subclass (ADR-0007).
"""

from __future__ import annotations

import httpx
import pytest
from langchain_core.messages import AIMessage

from ai_engine.core.providers.llm import client as client_module
from ai_engine.core.providers.llm.circuit_breaker import CircuitBreaker, CircuitOpenError
from ai_engine.core.providers.llm.client import AllLLMDownError, LLMClient, LLMResult


class _FakeChatModel:
    """Stands in for a BaseChatModel. Not a subclass: `invoke` is all
    `_attempt` touches, and subclassing drags in unrelated pydantic
    validation.
    """

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        reply = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


class _FakeLLM(LLMClient):
    def __init__(self, *replies, name="fake/model", cost=0.0, fallback=None):
        super().__init__(model_name=name, cost_per_1k_tokens=cost, fallback=fallback)
        self._model = _FakeChatModel(replies)

    def _build(self, timeout: float):
        return self._model

    @property
    def calls(self) -> int:
        return self._model.calls


def _ok(text='{"ok": true}', tokens_in=7, tokens_out=3):
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    )


@pytest.fixture(autouse=True)
def fresh_circuit(monkeypatch):
    """The client uses the process-wide breaker. Failures recorded by one test
    would otherwise open it for the next."""

    circuit = CircuitBreaker()
    monkeypatch.setattr(client_module, "CIRCUIT", circuit)
    return circuit


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)


# Content that is not a usable answer. Each of these would otherwise reach
# infer.py, fail `json.loads`, and be recorded as the MODEL producing bad
# output (proposal=None, no degraded_reason) when the real cause is upstream.
#
# A null content is absent here because it is unrepresentable: AIMessage
# rejects it at construction, so langchain-core turns it into an exception one
# layer below us, which the broad except in complete() already covers.
_UNUSABLE_CONTENT = {
    "empty string": "",
    "whitespace only": "   \n ",
    "content blocks": [{"type": "text", "text": '{"ok": true}'}],
}


@pytest.mark.parametrize("content", _UNUSABLE_CONTENT.values(), ids=_UNUSABLE_CONTENT.keys())
def test_unusable_content_raises_all_llm_down(content, no_backoff):
    """Blank or block-structured content is a transport-level failure, not a
    boring-but-valid proposal. It must exhaust the chain rather than be
    handed to infer.py as text."""

    primary = _FakeLLM(AIMessage(content=content))
    with pytest.raises(AllLLMDownError):
        primary.complete("s", "u", timeout=30.0)
    assert primary.calls == 2, "an unusable reply must be retried like a transport failure"


# Every hierarchy that can realistically escape a provider. Raw httpx errors;
# openai.APIError subclasses over vendored httpx2 (vLLM and the openai link) —
# and httpx.HTTPError is NOT httpx2.HTTPError. An enumerated except
# tuple in client.py would let one of these through as a 500.
_PROVIDER_ERRORS = {
    "httpx transport": httpx.ConnectTimeout("connect timed out"),
    "runtime": RuntimeError("provider not configured"),
    "value": ValueError("unparseable reply"),
    "bare exception": Exception("something from a dependency we don't import"),
}


@pytest.mark.parametrize("exc", _PROVIDER_ERRORS.values(), ids=_PROVIDER_ERRORS.keys())
def test_no_provider_exception_escapes_as_anything_but_all_llm_down(exc, no_backoff):
    """Guards the deliberately broad `except Exception` in complete(): every
    provider failure must reach infer.py as AllLLMDownError, or it becomes
    a 500 and the reviewer sees a blank panel.
    """

    with pytest.raises(AllLLMDownError):
        _FakeLLM(exc).complete("s", "u", timeout=30.0)


def test_circuit_open_is_not_swallowed_by_the_broad_except(fresh_circuit):
    """CircuitOpenError and AllLLMDownError map to DIFFERENT degraded_reason
    codes ("circuit_open" vs "all_llm_down"), and the HITL dashboard is built
    on that enum. The broad except in the retry loop must not blur them."""

    # Force the breaker open: >20% failures over at least 5 events.
    for _ in range(10):
        fresh_circuit.record(success=False)

    primary = _FakeLLM(_ok())
    with pytest.raises(CircuitOpenError):
        primary.complete("s", "u", timeout=30.0)
    assert primary.calls == 0, "an open circuit must not call any provider"


def test_failing_cloud_falls_back_to_self_host_and_marks_the_degradation(no_backoff):
    """The fallback is a quality degradation that core-api has to see: the
    trust score and the reviewer panel both read degraded_reason. Falling back
    silently would look like a clean cloud answer."""

    fallback = _FakeLLM(_ok(), name="vllm/Qwen/Qwen3-8B-AWQ")
    primary = _FakeLLM(RuntimeError("cloud down"), name="claude-sonnet-5", fallback=fallback)

    result = primary.complete("s", "u", timeout=30.0)

    assert result.degraded_reason == "cloud_fallback_to_self_host"
    assert result.model == "vllm/Qwen/Qwen3-8B-AWQ"
    assert primary.calls == 2, "the primary gets its retry before the chain falls back"
    assert fallback.calls == 1


def test_both_links_failing_raises_all_llm_down(no_backoff):
    fallback = _FakeLLM(httpx.ConnectError("vllm down"))
    primary = _FakeLLM(RuntimeError("cloud down"), fallback=fallback)
    with pytest.raises(AllLLMDownError):
        primary.complete("s", "u", timeout=30.0)


def test_absent_usage_metadata_defaults_to_zero_tokens():
    """A provider may omit token counts, so absent means 0, not
    an error (indistinguishable from null counts — ADR-0007).
    """

    result = _FakeLLM(AIMessage(content='{"ok": true}')).complete("s", "u", timeout=30.0)
    assert (result.tokens_in, result.tokens_out) == (0, 0)


def test_model_name_comes_from_config_not_the_response():
    """`ai_runs.model_used` has to be the model we ASKED for. A provider
    echoing a different name (a router, a quantisation suffix) must not change
    what the run is attributed to."""

    reply = _ok()
    reply.response_metadata["model"] = "something-else-entirely"
    result = _FakeLLM(reply, name="vllm/Qwen/Qwen3-8B-AWQ").complete("s", "u", timeout=30.0)
    assert result.model == "vllm/Qwen/Qwen3-8B-AWQ"


def test_cost_is_billed_at_the_providers_own_rate():
    """The rate lives on the provider. A client-side "is this the cloud link?"
    check would bill Gemini at Anthropic's rate, and the dashboard would
    look plausible while wrong.
    """

    result = _FakeLLM(_ok(tokens_in=900, tokens_out=100), cost=0.003).complete(
        "s", "u", timeout=30.0
    )
    assert result.tokens_in == 900
    assert result.cost_usd == pytest.approx(0.003)


def test_local_provider_is_free():
    result = _FakeLLM(_ok(tokens_in=1000, tokens_out=0), cost=0.0).complete("s", "u", timeout=30.0)
    assert result.cost_usd == 0.0, "self-hosted vLLM is local compute, treated as free"


def test_llm_result_rejects_a_null_text():
    """LLMResult validates on construction, so a None text cannot reach
    infer.py.
    """

    with pytest.raises(Exception):
        LLMResult(text=None, tokens_in=0, tokens_out=0, model="m", cost_usd=0.0)
