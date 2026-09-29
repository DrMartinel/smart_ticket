"""
Tier-2 PII NER tests (ADR-0012). This detector sees RAW ticket text, and
core-api masks exactly what it returns. There are three ways it goes wrong
silently:
- a failure comes back as [] and the ticket is filed as "no PII found",
- the raw text reaches `models.chat`, which may be a cloud provider,
- an error message carries the text or the model's reply into a log.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ai_engine.core.config import settings
from ai_engine.core.providers.llm import models
from ai_engine.core.providers.pii import PiiDetectionError, VllmPiiDetector

_RAW = "anh Tuấn phòng kế toán tầng 3 không in được"
_SECRET_REPLY = "chị Lan bàn cạnh cửa sổ"


class _ScriptedNer:
    """Stands in for `models.ner`: answers every request with one canned body
    (or raises it) and records what was sent."""

    def __init__(self, body):
        self._body = body
        self.sent: list[tuple[str, dict]] = []

    def request(self, path, payload):
        self.sent.append((path, payload))
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _chat_reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def serve_ner(monkeypatch):
    def install(body):
        client = _ScriptedNer(body)
        monkeypatch.setattr(models, "ner", client)
        return client

    return install


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


def test_ner_never_uses_the_chat_client(serve_ner, fake_llm, use_llm, monkeypatch):
    """`models.chat` may be OpenAI's cloud API (chat_client_provider=openai).
    Raw PII must only ever reach the self-hosted `models.ner` client."""

    monkeypatch.setattr(settings, "chat_client_provider", "openai")
    chat = use_llm(fake_llm())
    ner = serve_ner(_chat_reply(json.dumps({"spans": []})))

    VllmPiiDetector().detect(_RAW)

    assert chat.prompts == []
    assert len(ner.sent) == 1


def test_ner_client_is_the_self_hosted_chat_server(reload_models, monkeypatch):
    """Pins where `models.ner` points, whatever the chat provider is."""

    monkeypatch.setattr(settings, "chat_client_provider", "openai")
    monkeypatch.setattr(settings, "cloud_api_key", "sk-test")
    monkeypatch.setattr(settings, "cloud_model", "gpt-test")
    m = reload_models()

    assert type(m.ner) is m.VLLMLLM
    assert m.ner.base_url == settings.chat_base_url
    assert m.ner.model == settings.chat_model


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
