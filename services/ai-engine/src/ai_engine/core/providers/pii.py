"""
Tier-2 PII NER (spec §5, ADR-0012): finds the free-form PII that core-api's
regex tier misses, e.g. "anh Tuấn phòng kế toán tầng 3". core-api masks
what this returns, so this is the one place in ai-engine that sees RAW
ticket text.

Two rules follow from that:
- Raw text goes only to the self-hosted `models.ner` client, never to
  `models.chat`, which may be a cloud provider.
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

from ai_engine.core.config import settings
from ai_engine.core.prompts import load_system_prompt
from ai_engine.core.providers.llm import models

# Grammar-constrains the response so the parser never has to guess (vLLM
# structured outputs). The wrapper object exists because structured output is
# most reliable for objects; `spans` is the array we actually want.
_NER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"spans": {"type": "array", "items": {"type": "string"}}},
    "required": ["spans"],
}


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
    """NER on `chat_model` through `models.ner`, with a JSON-Schema-
    constrained reply. The prompt loads at construction, so a missing file
    fails the boot. Stateless."""

    def __init__(self) -> None:
        self._system_prompt = load_system_prompt(settings.pii_ner_prompt_version)

    def detect(self, text: str) -> list[str]:
        payload = {
            "model": settings.chat_model,
            # Instructions go in the system message, data in the user message.
            # Concatenating both into one string let the model read the
            # instructions as part of the conversation and *reply* to them — on
            # short subjects it would answer {"error": "please provide the text
            # to analyze"}, which the parser then rightly rejected, producing a
            # spurious MASK_FAILED for a ticket that simply had no free-form PII.
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": text},
            ],
            # A JSON *Schema*, not the bare json_object mode. That only
            # guarantees syntactically valid JSON and lets the model invent the
            # shape — in practice it returned {"found": [...]}, {"result": [...]},
            # a bare {}, an {"error": ...} object, and occasionally truncated
            # output. Every one of those became a spurious MASK_FAILED.
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ner_spans", "schema": _NER_RESPONSE_SCHEMA},
            },
            # qwen3 is a hybrid-thinking model; the reasoning trace is wasted
            # latency here and can crowd out the JSON we asked for.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            body = models.ner.request("/chat/completions", payload)
            # No default: a reply without content is a broken reply, not
            # "nothing found". Defaulting it to [] would resolve toward clean.
            parsed: Any = json.loads(body["choices"][0]["message"]["content"])
        except Exception as e:
            # Only the class name: an httpx or JSON error can quote the reply.
            raise PiiDetectionError(f"NER call failed: {type(e).__name__}") from e
        # The schema asks for {"spans": [...]}. The generic unwrap stays so a
        # backend that ignores the schema and wraps the array under another
        # key still works, rather than sending every ticket to a human.
        if isinstance(parsed, dict):
            parsed = next(filter(lambda v: isinstance(v, list), parsed.values()), None)
        if not isinstance(parsed, list):
            raise PiiDetectionError("unexpected NER reply shape")
        return [str(x) for x in parsed]


# --- The detector, built once when this module is imported --------------------
# Loads the prompt, so a missing prompt file is fatal at boot. Opens no socket.

pii_detector: PiiDetector = VllmPiiDetector()
