"""
LLM-client tests. The theme is where a malformed provider response ends up.
`LLMResult` validates on construction, so a provider that answers 200 with an
unusable body raises pydantic's ValidationError inside the client. That must
be handled like a transport failure — retry, fall back, then AllLLMDownError,
which the infer node maps to degraded_reason="all_llm_down" -> HITL. Escaping
the client would turn a degrade-to-human into a 500 with no TrustSignals.
"""

from __future__ import annotations

import httpx
import pytest

from ai_engine.core.config import settings
from ai_engine.llm import client as client_module
from ai_engine.llm.circuit_breaker import CircuitBreaker
from ai_engine.llm.client import AllLLMDownError, DefaultLLMClient, LLMResult

_OLLAMA_OK = {"response": '{"ok": true}', "prompt_eval_count": 7, "eval_count": 3}
_CLOUD_OK = {
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
}

# Every shape here used to escape the client — as a null `text`, or as a
# KeyError / IndexError / TypeError / JSONDecodeError from hand-indexing.
_MALFORMED_OLLAMA = {
    "null response": {**_OLLAMA_OK, "response": None},
    "missing response": {"prompt_eval_count": 7, "eval_count": 3},
    "null prompt_eval_count": {**_OLLAMA_OK, "prompt_eval_count": None},
    "null eval_count": {**_OLLAMA_OK, "eval_count": None},
    "not an object": ["response"],
    "not json": b"<html>502 Bad Gateway</html>",
}
_MALFORMED_CLOUD = {
    "null content": {**_CLOUD_OK, "choices": [{"message": {"content": None}}]},
    "missing choices": {"usage": _CLOUD_OK["usage"]},
    "empty choices": {**_CLOUD_OK, "choices": []},
    "null usage": {**_CLOUD_OK, "usage": None},
    "null token count": {**_CLOUD_OK, "usage": {"prompt_tokens": None}},
    "not json": b"upstream timeout",
}


def _fake_post(bodies_by_path: dict[str, object], calls: list[str]):
    def post(url, **kwargs):
        path = "/api/generate" if url.endswith("/api/generate") else "/v1/chat/completions"
        calls.append(path)
        body = bodies_by_path[path]
        request = httpx.Request("POST", url)
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, request=request)
        return httpx.Response(200, json=body, request=request)

    return post


@pytest.fixture
def cloud_configured(monkeypatch):
    monkeypatch.setattr(settings, "cloud_api_key", "key")
    monkeypatch.setattr(settings, "cloud_base_url", "https://cloud.example")


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)


@pytest.mark.parametrize("body", _MALFORMED_OLLAMA.values(), ids=_MALFORMED_OLLAMA.keys())
def test_malformed_ollama_response_raises_all_llm_down(body, monkeypatch, no_backoff):
    """Ollama is the primary (no cloud configured) and answers 200 with an
    unusable body twice. That is an exhausted provider, not a crash."""

    calls: list[str] = []
    monkeypatch.setattr(client_module.httpx, "post", _fake_post({"/api/generate": body}, calls))
    circuit = CircuitBreaker()

    with pytest.raises(AllLLMDownError):
        DefaultLLMClient(circuit=circuit).complete("SYSTEM", "USER", timeout=1.0)

    assert calls == ["/api/generate", "/api/generate"]  # retried once, like a transport error
    assert circuit._failure_rate() == 1.0  # and counted against the breaker


@pytest.mark.parametrize("body", _MALFORMED_CLOUD.values(), ids=_MALFORMED_CLOUD.keys())
def test_malformed_cloud_response_falls_back_to_ollama(
    body, monkeypatch, no_backoff, cloud_configured
):
    """A malformed cloud reply (null `content` is the refusal / tool-call
    shape) must take the same fallback path as a cloud outage."""

    calls: list[str] = []
    bodies = {"/v1/chat/completions": body, "/api/generate": _OLLAMA_OK}
    monkeypatch.setattr(client_module.httpx, "post", _fake_post(bodies, calls))

    result = DefaultLLMClient(circuit=CircuitBreaker()).complete("SYSTEM", "USER", timeout=1.0)

    assert isinstance(result, LLMResult)
    assert result.degraded_reason == "cloud_fallback_to_ollama"
    assert calls == ["/v1/chat/completions", "/v1/chat/completions", "/api/generate"]


def test_llm_result_rejects_a_null_text():
    """Pins the validation the two tests above depend on: if LLMResult stops
    validating, a null body would reach the infer node as text=None."""

    with pytest.raises(ValueError):
        LLMResult(text=None, tokens_in=1, tokens_out=1, model="m", cost_usd=0.0)


def test_malformed_cloud_and_ollama_raise_all_llm_down(monkeypatch, no_backoff, cloud_configured):
    """The fallback call is the last line: a malformed Ollama body there must
    also end in AllLLMDownError rather than escaping."""

    bodies = {"/v1/chat/completions": {}, "/api/generate": b"not json"}
    monkeypatch.setattr(client_module.httpx, "post", _fake_post(bodies, []))

    with pytest.raises(AllLLMDownError):
        DefaultLLMClient(circuit=CircuitBreaker()).complete("SYSTEM", "USER", timeout=1.0)


def test_absent_token_counts_default_to_zero(monkeypatch, no_backoff):
    """Absent is not malformed: Ollama omits `prompt_eval_count` when the
    prompt was cached. Only a NULL count is rejected — see the cases above."""

    body = {"response": '{"ok": true}'}
    monkeypatch.setattr(client_module.httpx, "post", _fake_post({"/api/generate": body}, []))

    result = DefaultLLMClient(circuit=CircuitBreaker()).complete("SYSTEM", "USER", timeout=1.0)

    assert (result.tokens_in, result.tokens_out) == (0, 0)
