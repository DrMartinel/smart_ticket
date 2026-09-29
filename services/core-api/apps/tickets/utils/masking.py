"""
Masking Engine — spec §5. Runs INLINE, before any write to the `tickets`
table. If masking were async, there would exist a moment where raw PII sat
in the DB or on the broker; that moment is the vulnerability this design
avoids entirely.

Two-tier pipeline:
  Tier 1 — regex: fast, high-confidence, structured patterns. CRITICAL
           hits (password/token/API key) short-circuit before the LLM is
           even called.
  Tier 2 — self-hosted LLM, via ai-engine's `/v1/pii/detect` (ADR-0012):
           catches free-form PII regex misses, e.g.
           "anh Tuấn phòng kế toán tầng 3". A timeout or error here becomes
           PIILevel.MASK_FAILED, never "treat as clean" — uncertainty must
           cost a human's time, not risk a leak (spec §5.2).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from apps.tickets.utils.patterns import PIILevel
from apps.tickets.request_schema import TicketIn
from infrastructure.ai_engine import ai_engine

from .patterns import ALL_GROUPS, LEVEL_BY_GROUP

logger = logging.getLogger(__name__)


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


class NERError(Exception):
    pass


def regex_scan(text: str) -> list[PIIHit]:
    hits = []
    for group, patterns in ALL_GROUPS.items():
        level = LEVEL_BY_GROUP[group]
        for label, pattern in patterns.items():
            for m in pattern.finditer(text):
                hits.append(
                    PIIHit(label=label, level=level, start=m.start(), end=m.end(), value=m.group())
                )
    return hits


def regex_scan_ticket(raw: TicketIn) -> ScanResult:
    """Subject and body are scanned independently — each field's hit
    offsets are only ever used to mask that same field, so there's no need
    to reconcile them into a single combined offset space."""
    return ScanResult(hits=regex_scan(raw.subject) + regex_scan(raw.body))


async def llm_ner(text: str) -> list[str]:
    """Tier 2, run by ai-engine on the self-hosted chat model (ADR-0012), which
    owns the prompt and the reply parsing. Raises NERError/TimeoutError on any
    failure — callers MUST treat that as MASK_FAILED, never as "no PII found".

    The error message carries the exception class only: an error about the
    request or the reply can quote the text, which is raw PII, and the
    caller logs it.
    """

    try:
        return await ai_engine.detect_pii(text)
    except httpx.TimeoutException as e:
        raise TimeoutError(type(e).__name__) from e
    except (httpx.HTTPError, ValueError) as e:
        raise NERError(type(e).__name__) from e


def _mask_field(
    text: str, hits: list[PIIHit], counters: dict[str, int], placeholder_map: dict[str, str]
) -> str:
    """Replace hits with numbered placeholders, right-to-left so earlier
    offsets stay valid. Placeholders are numbered per-label so repeated
    mentions of the same email keep their "same entity" relationship
    (spec §5.2) — the value is looked up in `placeholder_map` if the exact
    substring was already seen for that label.
    """
    ordered = sorted(hits, key=lambda h: h.start, reverse=True)
    for h in ordered:
        existing = next(
            (
                ph
                for ph, val in placeholder_map.items()
                if val == h.value and ph.startswith(f"[{h.label}_")
            ),
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


def _apply(
    raw: TicketIn, subject_hits: list[PIIHit], body_hits: list[PIIHit]
) -> tuple[str, str, dict[str, str], PIILevel]:
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
        # before anything — including the LLM — is called again.
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
            llm_ner(raw.subject), llm_ner(raw.body)
        )
    except (TimeoutError, NERError) as e:
        logger.warning(
            "masking: LLM NER failed (%s) — flagging MASK_FAILED, not treating as clean", e
        )
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
        hits.append(
            PIIHit(
                label="FREEFORM", level=PIILevel.ROUTINE, start=idx, end=idx + len(span), value=span
            )
        )
    return hits
