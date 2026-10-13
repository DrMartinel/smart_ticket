"""
Tier-2 PII NER (spec §5, ADR-0012): finds the free-form PII that core-api's
regex tier misses, e.g. "anh Tuấn phòng kế toán tầng 3". core-api masks
what this returns, so this is the one place in ai-engine that sees RAW
ticket text.

Two rules follow from that:
- Raw text goes only to the self-hosted `clients.ner` client, never to
  `clients.chat`, which may be a cloud provider. The one exception is
  `NER_CLIENT_PROVIDER=deepseek` (ADR-0019, evaluation only), which sends
  raw ticket text to DeepSeek's hosted API by explicit decision. It has its
  own setting so that pointing the proposal or the draft at DeepSeek never
  sends raw text there as a side effect.
- No error message, log line or exception carries the text or the model's
  output. The model's output IS the PII.

There is deliberately no offline implementation. A stub that finds nothing
would be "no PII found" on every ticket: the worst regression this system
can have (CLAUDE.md rule 3). Without vLLM, masking fails closed to
`mask_failed` instead.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ai_engine.core.config import settings
from ai_engine.core.prompts import PII_NER_PROMPT
from ai_engine.core.providers import clients

# Greedy decoding. Sampled (vLLM's default for the model, ~0.7 for Qwen3), the
# same ticket masked differently from call to call: cleanly once, with its
# request masked away the next (g148, evals/HISTORY.md 2026-10-04 (2)).
# Masking must be repeatable, so it can be reviewed and measured.
_GREEDY = 0.0


class PiiDetectionError(Exception):
    """NER could not produce an answer. core-api MUST treat this as
    MASK_FAILED, never as "no PII found". The message never contains the
    text or the model output."""


class PiiDetector(ABC):
    """What `POST /v1/pii/detect` depends on."""

    @abstractmethod
    def detect(self, text: str) -> list[str]:
        """Exact substrings of `text` that are free-form PII; [] means the
        model found none. Raises `PiiDetectionError` on any failure — never
        returns [] for one, which would read as "clean"."""


class VllmPiiDetector(PiiDetector):
    """NER on `chat_model` through `clients.ner`, with a JSON-Schema-
    constrained reply. Stateless."""

    def detect(self, text: str) -> list[str]:
        try:
            parsed: Any = clients.ner.complete_json(
                PII_NER_PROMPT,
                text,
                schema_name="ner_spans",
                schema={
                    "type": "object",
                    "properties": {"spans": {"type": "array", "items": {"type": "string"}}},
                    "required": ["spans"],
                },
                temperature=_GREEDY,
            )
        except Exception as e:
            raise PiiDetectionError(f"NER call failed: {type(e).__name__}") from e
        if isinstance(parsed, dict):
            parsed = next((v for v in parsed.values() if isinstance(v, list)), None)
        if not isinstance(parsed, list):
            raise PiiDetectionError("unexpected NER reply shape")
        return [str(x) for x in parsed]


class DeepSeekPiiDetector(PiiDetector):
    """NER on DeepSeek's hosted API (ADR-0019): raw ticket text leaves the
    machine. DeepSeek decodes against no schema, so the reply is a plain
    JSON object, validated here, at temperature 0 for repeatable masking.
    Calls the model directly rather than through `ChatClient`, whose errors
    quote the reply. Stateless."""

    def __init__(self) -> None:
        self._model = clients.ChatClient.deepseek_model(json_mode=True, temperature=_GREEDY)

    def detect(self, text: str) -> list[str]:
        try:
            reply = self._model.invoke([SystemMessage(PII_NER_PROMPT), HumanMessage(text)])
            parsed: Any = json.loads(reply.content if isinstance(reply.content, str) else "")
        except Exception as e:
            raise PiiDetectionError(f"NER call failed: {type(e).__name__}") from None
        spans = parsed.get("spans") if isinstance(parsed, dict) else None
        if not isinstance(spans, list):
            raise PiiDetectionError("unexpected NER reply shape")
        return [str(x) for x in spans]


# --- The detector, built once when this module is imported (no I/O) ----------
# NER leaves the machine only when its own setting says DeepSeek (ADR-0019),
# whatever model the proposal or the draft runs on.

pii_detector: PiiDetector = (
    DeepSeekPiiDetector() if settings.ner_client_provider == "deepseek" else VllmPiiDetector()
)
