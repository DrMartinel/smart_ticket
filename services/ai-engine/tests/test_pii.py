"""
Tier-2 PII NER tests (ADR-0012). This detector sees RAW ticket text, and
core-api masks exactly what it returns. There are three ways it goes wrong
silently:
- a failure comes back as [] and the ticket is filed as "no PII found",
- the raw text reaches `clients.chat`, which may be a cloud provider,
- an error message carries the text or the model's reply into a log.
"""

from __future__ import annotations

import json
import traceback

import httpx
import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.pii import PiiDetectionError, VllmPiiDetector

_RAW = "anh Tuấn phòng kế toán tầng 3 không in được"
_SECRET_REPLY = "chị Lan bàn cạnh cửa sổ"


def _chat_reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def serve_ner(serve):
    return lambda body: serve("ner", body)


# --- failure paths first ------------------------------------------------------

_BROKEN = {
    "server error": httpx.HTTPStatusError(
        "503", request=httpx.Request("POST", "http://x"), response=httpx.Response(503)
    ),
    "connect error": httpx.ConnectError("unreachable"),
    "timeout": httpx.ReadTimeout("slow"),
    "no choices": {"choices": []},
    "no content": {"choices": [{"message": {}}]},
    "null content": _chat_reply("null"),
    "not json": _chat_reply("I could not find any"),
    "error object": _chat_reply(json.dumps({"error": "please provide the text"})),
    "bare string": _chat_reply(json.dumps("anh Tuấn")),
}


@pytest.mark.parametrize("body", _BROKEN.values(), ids=_BROKEN.keys())
def test_any_failure_raises_rather_than_reading_as_no_pii(serve_ner, body):
    """Every one of these used to be (or could become) [] somewhere, which
    core-api would file as a clean ticket. They must raise, so core-api
    resolves them to MASK_FAILED."""

    serve_ner(body)
    with pytest.raises(PiiDetectionError):
        VllmPiiDetector().detect(_RAW)


@pytest.mark.parametrize(
    "content",
    [json.dumps(_SECRET_REPLY), f"Found: {_SECRET_REPLY}"],
    ids=["wrong shape", "not json"],
)
def test_error_message_never_carries_the_text_or_the_reply(serve_ner, content):
    """The text and the model's reply are both PII, and the error message
    ends up in logs."""

    serve_ner(_chat_reply(content))

    with pytest.raises(PiiDetectionError) as caught:
        VllmPiiDetector().detect(_RAW)

    assert _RAW not in str(caught.value)
    assert _SECRET_REPLY not in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        _chat_reply(f"Found: {_SECRET_REPLY}"),
        {"choices": [{"message": {"content": [_SECRET_REPLY]}}]},
    ],
    ids=["not json", "malformed envelope"],
)
def test_the_logged_traceback_never_carries_the_reply(serve_ner, body):
    """A Pydantic ValidationError quotes its input. Logged with exc_info, a
    chained one would print the model's reply, which is PII, so the client
    must not chain it."""

    serve_ner(body)

    with pytest.raises(PiiDetectionError) as caught:
        VllmPiiDetector().detect(_RAW)

    logged = "".join(traceback.format_exception(caught.value))
    assert _SECRET_REPLY not in logged


def test_ner_never_uses_the_chat_client(serve_ner, fake_llm, use_llm, monkeypatch):
    """`clients.chat` may be OpenAI's cloud API (chat_client_provider=openai).
    Raw PII must only ever reach the self-hosted `clients.ner` client."""

    monkeypatch.setattr(settings, "chat_client_provider", "openai")
    chat = use_llm(fake_llm())
    ner = serve_ner(_chat_reply(json.dumps({"spans": []})))

    VllmPiiDetector().detect(_RAW)

    assert chat.prompts == []
    assert len(ner.sent) == 1


def test_ner_client_is_the_self_hosted_chat_server(reload_clients, monkeypatch):
    """Pins where `clients.ner` points, whatever the chat provider is."""

    monkeypatch.setattr(settings, "chat_client_provider", "openai")
    monkeypatch.setattr(settings, "cloud_api_key", "sk-test")
    monkeypatch.setattr(settings, "cloud_model", "gpt-test")
    m = reload_clients()

    assert type(m.ner) is m.VLLMClient
    assert m.ner.base_url == settings.chat_base_url


# --- DeepSeek (ADR-0019): raw text leaves the machine, by decision -------------


class _ScriptedModel:
    """Stands in for DeepSeek's chat model: returns `content` or raises."""

    def __init__(self, content: object = None, error: Exception | None = None) -> None:
        self.content, self.error = content, error
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return type("Reply", (), {"content": self.content})()


@pytest.fixture
def deepseek_ner(monkeypatch):
    from ai_engine.core.providers import pii

    def use(model: _ScriptedModel) -> pii.DeepSeekPiiDetector:
        monkeypatch.setattr(pii.clients.ChatClient, "deepseek_model", lambda **_: model)
        return pii.DeepSeekPiiDetector()

    return use


@pytest.mark.parametrize(
    "model",
    [
        _ScriptedModel(error=RuntimeError("down")),
        _ScriptedModel(content=""),
        _ScriptedModel(content="I could not find any"),
        _ScriptedModel(content=json.dumps(["anh Tuấn"])),
        _ScriptedModel(content=json.dumps({"error": "no"})),
        _ScriptedModel(content=[_SECRET_REPLY]),
    ],
    ids=["call fails", "empty", "not json", "bare list", "no spans", "not a string"],
)
def test_deepseek_failures_raise_rather_than_reading_as_no_pii(deepseek_ner, model):
    """DeepSeek decodes against no schema, and its JSON mode 'may
    occasionally return empty content' (its docs). None of these may come
    back as [], which core-api would file as a clean ticket."""
    with pytest.raises(PiiDetectionError):
        deepseek_ner(model).detect(_RAW)


@pytest.mark.parametrize(
    "model",
    [
        _ScriptedModel(content=f"Found: {_SECRET_REPLY}"),
        _ScriptedModel(error=ValueError(f"bad reply {_SECRET_REPLY}")),
    ],
    ids=["not json", "error quoting the reply"],
)
def test_deepseek_errors_and_tracebacks_never_carry_the_text_or_reply(deepseek_ner, model):
    with pytest.raises(PiiDetectionError) as caught:
        deepseek_ner(model).detect(_RAW)

    logged = "".join(traceback.format_exception(caught.value))
    assert _RAW not in logged and _SECRET_REPLY not in logged


def test_deepseek_ner_reads_spans_greedily(monkeypatch):
    """Sampled, the same ticket masks differently call to call (g148)."""
    from ai_engine.core.providers import pii

    built = {}
    model = _ScriptedModel(content=json.dumps({"spans": [_SECRET_REPLY]}))
    monkeypatch.setattr(
        pii.clients.ChatClient, "deepseek_model", lambda **kw: built.update(kw) or model
    )

    assert pii.DeepSeekPiiDetector().detect(_RAW) == [_SECRET_REPLY]
    assert built == {"json_mode": True, "temperature": 0.0}
    system, user = model.calls[0]
    assert (system.content, user.content) == (pii.PII_NER_PROMPT, _RAW)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("vllm", "VllmPiiDetector"),
        ("deepseek", "DeepSeekPiiDetector"),
    ],
)
def test_only_ner_set_to_deepseek_sends_raw_text_off_the_machine(provider, expected, monkeypatch):
    """NER reads the raw ticket, so only its own setting may move it to
    DeepSeek (ADR-0019, evaluation only)."""
    import importlib

    from ai_engine.core.providers import pii

    monkeypatch.setattr(settings, "ner_client_provider", provider)
    monkeypatch.setattr(pii.clients.ChatClient, "deepseek_model", lambda **_: _ScriptedModel())
    saved = dict(vars(pii))
    try:
        reloaded = importlib.reload(pii)
        assert type(reloaded.pii_detector).__name__ == expected
    finally:
        vars(pii).update(saved)


# --- behaviour ------------------------------------------------------------------


def test_spans_are_read_from_the_schema_constrained_reply(serve_ner):
    serve_ner(_chat_reply(json.dumps({"spans": ["anh Tuấn phòng kế toán tầng 3"]})))
    assert VllmPiiDetector().detect(_RAW) == ["anh Tuấn phòng kế toán tầng 3"]


def test_an_empty_list_is_a_real_answer(serve_ner):
    serve_ner(_chat_reply(json.dumps({"spans": []})))
    assert VllmPiiDetector().detect(_RAW) == []


@pytest.mark.parametrize(
    "content",
    [json.dumps(["anh Tuấn"]), json.dumps({"found": ["anh Tuấn"]})],
    ids=["bare array", "other wrapper key"],
)
def test_a_backend_that_ignores_the_schema_still_parses(serve_ner, content):
    """A backend that ignores the JSON Schema must not send every ticket to a
    human just for wrapping the array differently."""

    serve_ner(_chat_reply(content))
    assert VllmPiiDetector().detect(_RAW) == ["anh Tuấn"]


def test_request_puts_instructions_and_data_in_separate_messages(serve_ner):
    """Concatenated, the model replied to the instructions instead of
    analysing the text, which surfaced as spurious MASK_FAILEDs."""

    ner = serve_ner(_chat_reply(json.dumps({"spans": []})))

    VllmPiiDetector().detect(_RAW)

    path, payload = ner.sent[0]
    assert path == "/chat/completions"
    assert payload["model"] == settings.chat_model
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]
    assert payload["messages"][1]["content"] == _RAW
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"]["required"] == ["spans"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_ner_decodes_greedily(serve_ner):
    """Sampled, the same ticket masked differently from call to call, once
    with its request masked away (evals/HISTORY.md 2026-10-04 (2))."""

    ner = serve_ner(_chat_reply(json.dumps({"spans": []})))

    VllmPiiDetector().detect(_RAW)

    _, payload = ner.sent[0]
    assert payload["temperature"] == 0.0


@pytest.mark.parametrize("other", ["chat_client_provider", "draft_client_provider"])
def test_the_proposal_or_draft_on_deepseek_keeps_ner_local(other, monkeypatch):
    """Before NER had its own setting, CHAT_CLIENT_PROVIDER=deepseek moved
    the raw ticket to DeepSeek too, as a side effect of choosing the
    proposal's model. Raw text must stay local unless NER itself is pointed
    at DeepSeek."""
    import importlib

    from ai_engine.core.providers import pii

    monkeypatch.setattr(settings, other, "deepseek")
    monkeypatch.setattr(settings, "ner_client_provider", "vllm")
    saved = dict(vars(pii))
    try:
        reloaded = importlib.reload(pii)
        assert type(reloaded.pii_detector).__name__ == "VllmPiiDetector"
    finally:
        vars(pii).update(saved)
