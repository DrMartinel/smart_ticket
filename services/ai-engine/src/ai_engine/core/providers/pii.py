"""
Tier-2 PII NER (spec §5, ADR-0012): finds the free-form PII that core-api's
regex tier misses, e.g. "anh Tuấn phòng kế toán tầng 3". core-api masks
what this returns, so this is the one place in ai-engine that sees RAW
ticket text.

Two rules follow from that:
- Raw text goes only to the self-hosted `clients.ner` client, never to
  `clients.chat`, which may be a cloud provider.
- No error message, log line or exception carries the text or the model's
  output. The model's output IS the PII.

There is deliberately no offline implementation. A stub that finds nothing
would be "no PII found" on every ticket: the worst regression this system
can have (CLAUDE.md rule 3). Without vLLM, masking fails closed to
`mask_failed` instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ai_engine.core.prompts import PII_NER_PROMPT
from ai_engine.core.providers import clients


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
            )
        except Exception as e:
            raise PiiDetectionError(f"NER call failed: {type(e).__name__}") from e
        if isinstance(parsed, dict):
            parsed = next((v for v in parsed.values() if isinstance(v, list)), None)
        if not isinstance(parsed, list):
            raise PiiDetectionError("unexpected NER reply shape")
        return [str(x) for x in parsed]


# --- The detector, built once when this module is imported (no I/O) ----------

pii_detector: PiiDetector = VllmPiiDetector()
