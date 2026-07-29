"""
Masking Engine — spec §5. Runs INLINE, before any write to the `tickets`
table. If masking were async, there would exist a moment where raw PII sat
in the DB or on the broker; that moment is the vulnerability this design
avoids entirely.

Two-tier pipeline:
  Tier 1 — regex: fast, high-confidence, structured patterns. CRITICAL
           hits (password/token/API key) short-circuit before Ollama is
           even called.
  Tier 2 — local LLM (Ollama): catches free-form PII regex misses, e.g.
           "anh Tuấn phòng kế toán tầng 3". A timeout or error here becomes
           PIILevel.MASK_FAILED, never "treat as clean" — uncertainty must
           cost a human's time, not risk a leak (spec §5.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import httpx
from django.conf import settings

from contracts.enums import PIILevel
from contracts.ticket import TicketIn

from .patterns import ALL_GROUPS, LEVEL_BY_GROUP

logger = logging.getLogger(__name__)

def _ner_timeout() -> httpx.Timeout:
    """Read at call time, not import time, so tests and `override_settings`
    can adjust it without reloading the module.

    Connect and read are budgeted separately on purpose — see
    OLLAMA_CONNECT_TIMEOUT_SEC in settings. An unreachable provider is
    knowable in seconds; only a *reachable but busy* one deserves the
    full read budget.
    """
    read = float(getattr(settings, "OLLAMA_TIMEOUT_SEC", 120.0))
    connect = float(getattr(settings, "OLLAMA_CONNECT_TIMEOUT_SEC", 3.0))
    return httpx.Timeout(read, connect=connect)

_NER_SYSTEM_PROMPT = """\
You detect personally-identifiable free-form mentions in IT support tickets
written in Vietnamese and/or English: full names, specific desk/room/floor
locations, department + person combinations, and similar identifying
details that a regex pattern would miss (NOT emails, phone numbers, IDs,
IPs, or account numbers — those are already handled separately).

Return ONLY a JSON array of exact substrings found in the text, e.g.:
["anh Tuấn phòng kế toán tầng 3", "chị Lan bàn cạnh cửa sổ"]

Rules:
- Return [] if you find nothing. An empty array is a valid, expected answer.
- Return [] for short, terse, or seemingly incomplete input too. Never ask
  for more input and never return an error object — the user message is
  always the text to analyze, exactly as given.
- Output the array and nothing else.
"""

# Grammar-constrains the response so the parser never has to guess. The
# wrapper object exists because Ollama's structured-output support is
# reliable for objects; `spans` is the array we actually want.
_NER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"spans": {"type": "array", "items": {"type": "string"}}},
    "required": ["spans"],
}


@dataclass(frozen=True)
class PIIHit:
    label: str
    level: PIILevel
    start: int
    end: int
    value: str


@dataclass(frozen=True)
class ScanResult:
    hits: list[PIIHit]

    @property
    def has_critical(self) -> bool:
        return any(h.level is PIILevel.CRITICAL for h in self.hits)


class OllamaError(Exception):
    pass


def regex_scan(text: str) -> list[PIIHit]:
    hits: list[PIIHit] = []
    for group, patterns in ALL_GROUPS.items():
        level = LEVEL_BY_GROUP[group]
        for label, pattern in patterns.items():
            for m in pattern.finditer(text):
                hits.append(PIIHit(label=label, level=level, start=m.start(), end=m.end(), value=m.group()))
    return hits


def regex_scan_ticket(raw: TicketIn) -> ScanResult:
    """Subject and body are scanned independently — each field's hit
    offsets are only ever used to mask that same field, so there's no need
    to reconcile them into a single combined offset space."""
    return ScanResult(hits=regex_scan(raw.subject) + regex_scan(raw.body))


async def ollama_ner(text: str, timeout: float | httpx.Timeout | None = None) -> list[str]:
    """Tier 2. Raises OllamaError/TimeoutError on any failure — callers
    MUST treat that as MASK_FAILED, never as "no PII found"."""

    if timeout is None:
        timeout = _ner_timeout()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_NER_MODEL,
        # Instructions go in `system`, data in `prompt`. Concatenating both
        # into one string let the model read the instructions as part of
        # the conversation and *reply* to them — on short subjects it would
        # answer {"error": "please provide the text to analyze"}, which the
        # parser then rightly rejected, producing a spurious MASK_FAILED
        # for a ticket that simply had no free-form PII.
        "system": _NER_SYSTEM_PROMPT,
        "prompt": text,
        "stream": False,
        # A JSON *Schema*, not the bare "json" mode. "json" only guarantees
        # syntactically valid JSON and lets the model invent the shape — in
        # practice it returned {"found": [...]}, {"result": [...]}, a bare
        # {}, an {"error": ...} object, and occasionally truncated output.
        # Every one of those became a spurious MASK_FAILED. Constraining
        # the grammar makes the shape a guarantee instead of a hope.
        "format": _NER_RESPONSE_SCHEMA,
        # qwen3 is a hybrid-thinking model; the reasoning trace is wasted
        # latency here and can crowd out the JSON we asked for.
        "think": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_out = data.get("response", "[]")
            parsed = json.loads(raw_out)
            # Ollama's format="json" guarantees valid JSON, not a top-level
            # array — models routinely wrap the array in an object (e.g.
            # {"found": [...]}) despite the prompt asking for a bare array.
            # Unwrap the first list value found rather than treating that
            # shape as an error, which would otherwise flag every ticket as
            # MASK_FAILED regardless of whether any PII was actually found.
            # With the schema above this is `spans`; the generic fallback
            # stays so a provider that ignores the schema (or a different
            # backend entirely) still degrades gracefully rather than
            # sending every ticket to a human.
            if isinstance(parsed, dict):
                parsed = next((v for v in parsed.values() if isinstance(v, list)), None)
            if not isinstance(parsed, list):
                raise OllamaError(f"unexpected NER response shape: {raw_out!r}")
            return [str(x) for x in parsed]
    except httpx.TimeoutException as e:
        raise TimeoutError(str(e)) from e
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
        raise OllamaError(str(e)) from e


def _mask_field(text: str, hits: list[PIIHit], counters: dict[str, int], placeholder_map: dict[str, str]) -> str:
    """Replace hits with numbered placeholders, right-to-left so earlier
    offsets stay valid. Placeholders are numbered per-label so repeated
    mentions of the same email keep their "same entity" relationship
    (spec §5.2) — the value is looked up in `placeholder_map` if the exact
    substring was already seen for that label.
    """
    ordered = sorted(hits, key=lambda h: h.start, reverse=True)
    for h in ordered:
        existing = next(
            (ph for ph, val in placeholder_map.items() if val == h.value and ph.startswith(f"[{h.label}_")),
            None,
        )
        if existing:
            placeholder = existing
        else:
            counters[h.label] = counters.get(h.label, 0) + 1
            placeholder = f"[{h.label}_{counters[h.label]}]"
            placeholder_map[placeholder] = h.value
        text = text[: h.start] + placeholder + text[h.end :]
    return text


def _apply(raw: TicketIn, subject_hits: list[PIIHit], body_hits: list[PIIHit]) -> tuple[str, str, dict[str, str], PIILevel]:
    counters: dict[str, int] = {}
    placeholder_map: dict[str, str] = {}

    subject_masked = _mask_field(raw.subject, subject_hits, counters, placeholder_map)
    body_masked = _mask_field(raw.body, body_hits, counters, placeholder_map)

    all_hits = subject_hits + body_hits
    if any(h.level is PIILevel.SENSITIVE for h in all_hits):
        level = PIILevel.SENSITIVE
    elif all_hits:
        level = PIILevel.ROUTINE
    else:
        level = PIILevel.ROUTINE

    return subject_masked, body_masked, placeholder_map, level


@dataclass(frozen=True)
class MaskResult:
    subject_masked: str
    body_masked: str
    pii_level: PIILevel
    placeholder_map: dict[str, str]  # placeholder -> real value, for quarantine


async def mask(raw: TicketIn) -> MaskResult:
    """Returns the masked ticket plus the placeholder -> real value map to
    hand to the quarantine store. Attachments are never inspected here —
    they are treated as fully untrusted (spec §5.2) and are not masked or
    quoted anywhere in the pipeline; ai-engine's injection detector treats
    them as the most likely indirect-injection vector.
    """

    subject_hits = regex_scan(raw.subject)
    body_hits = regex_scan(raw.body)

    if any(h.level is PIILevel.CRITICAL for h in subject_hits + body_hits):
        # BLOCK path: mask what we found (so nothing raw is ever returned)
        # but flag CRITICAL so router.py hard-gates this ticket immediately,
        # before anything — including Ollama — is called again.
        subject_masked, body_masked, placeholder_map, _ = _apply(raw, subject_hits, body_hits)
        return MaskResult(subject_masked, body_masked, PIILevel.CRITICAL, placeholder_map)

    try:
        # Run the two NER calls concurrently. They are independent (each
        # field's spans only ever mask that same field), and masking is
        # INLINE in the submit request — sequential calls would make the
        # worst case two full timeouts deep, which at a 120s per-call
        # budget would outlast the gunicorn request timeout and turn a
        # clean MASK_FAILED into a 502.
        llm_subject_spans, llm_body_spans = await asyncio.gather(
            ollama_ner(raw.subject), ollama_ner(raw.body)
        )
    except (TimeoutError, OllamaError) as e:
        logger.warning("masking: Ollama NER failed (%s) — flagging MASK_FAILED, not treating as clean", e)
        subject_masked, body_masked, placeholder_map, _ = _apply(raw, subject_hits, body_hits)
        return MaskResult(subject_masked, body_masked, PIILevel.MASK_FAILED, placeholder_map)

    llm_subject_hits = _spans_to_hits(raw.subject, llm_subject_spans)
    llm_body_hits = _spans_to_hits(raw.body, llm_body_spans)

    subject_masked, body_masked, placeholder_map, level = _apply(
        raw, subject_hits + llm_subject_hits, body_hits + llm_body_hits
    )
    return MaskResult(subject_masked, body_masked, level, placeholder_map)


def _spans_to_hits(text: str, spans: list[str]) -> list[PIIHit]:
    hits = []
    for span in spans:
        idx = text.find(span)
        if idx == -1 or not span.strip():
            continue
        hits.append(PIIHit(label="FREEFORM", level=PIILevel.ROUTINE, start=idx, end=idx + len(span), value=span))
    return hits
