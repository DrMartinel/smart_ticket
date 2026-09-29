"""
Validator — spec §6.4. Four checks, in the spec's order:

1. Exact substring match — cheap and unambiguous.
2. Fuzzy match gated at 0.95, only for whitespace/punctuation drift.
3. The quote's source chunk must be in the retrieved top-k; a verbatim quote
   from the WRONG article is still a wrong answer.
4. Negation: "được cấp quyền" vs "không được cấp quyền" (or "delete the
   root user access keys" vs "Do not delete the root user access keys") score
   ~0.96 similarity with opposite meanings, and negated conditions are common
   in runbook-style KB content. The quote is compared with the sentence(s) it
   was cut from, not the whole chunk: a 250-word AWS chunk nearly always has
   a "not" somewhere, and comparing against all of it would flag every
   English quote.
"""

from __future__ import annotations

import uuid

import re

from rapidfuzz import fuzz

from ai_engine.core.state import AutoReplyProposal, TriageState

from ai_engine.core.config import settings
from ai_engine.core.node import BaseNode, StateUpdate

# Linguistic lexicons, not tunable numbers — they belong in code for the
# same reason patterns.py holds the PII regexes. Vietnamese phrases are
# matched as substrings. English is matched on word boundaries, since "not"
# and "no" are inside "notification" and "node". The demo KB is English
# (demo_kb/), and tickets may be in either language.
NEGATIONS = {"không", "chưa", "ngoại trừ", "trừ khi", "không được", "cấm"}
ENGLISH_NEGATION = re.compile(
    r"\b(?:not|no|never|cannot|none|nor|without|except|unless)\b|\b\w+n['’]t\b",
    re.IGNORECASE,
)
# End of a sentence, or a line break (a Markdown list item or heading).
_SENTENCE_BREAK = re.compile(r"[.!?](?=\s)|\n")


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _negations_in(text: str, negations: set[str]) -> frozenset[str]:
    lowered = text.lower()
    vietnamese = {neg for neg in negations if neg in lowered}
    english = {m.group(0).lower().replace("’", "'") for m in ENGLISH_NEGATION.finditer(text)}
    return frozenset(vietnamese | english)


def _enclosing_sentences(quote: str, content: str) -> str:
    """The sentence(s) of `content` the quote was cut from.

    Found in the raw chunk, whitespace-tolerant, so line breaks still mark
    list items. A fuzzy-only match is located by alignment instead. If the
    quote can't be located at all, the whole chunk is returned, which only
    makes the check stricter."""

    words = quote.split()
    found = re.search(r"\s+".join(map(re.escape, words)), content) if words else None
    if found:
        start, end = found.span()
    else:
        alignment = fuzz.partial_ratio_alignment(quote, content)
        if alignment is None:
            return content
        start, end = alignment.dest_start, alignment.dest_end
    breaks_before = [m.end() for m in _SENTENCE_BREAK.finditer(content, 0, start)]
    # From end - 1, so a period that ends the quote closes its sentence.
    after = _SENTENCE_BREAK.search(content, max(start, end - 1))
    return content[
        breaks_before[-1] if breaks_before else 0 : after.end() if after else len(content)
    ]


def _best_fuzzy(quote: str, topk: dict[uuid.UUID, str]) -> tuple[uuid.UUID | None, float]:
    best_id, best_ratio = None, 0.0
    for chunk_id, content in topk.items():
        ratio = fuzz.ratio(quote, content) / 100.0
        # fuzz.ratio is whole-string similarity; for a short quote inside a
        # long chunk we also check the best partial-ratio alignment so a
        # verbatim quote embedded in a much longer chunk isn't penalized
        # just for the chunk being long.
        partial = fuzz.partial_ratio(quote, content) / 100.0
        ratio = max(ratio, partial)
        if ratio > best_ratio:
            best_id, best_ratio = chunk_id, ratio
    return best_id, best_ratio


def _checks(
    *,
    schema_valid: bool,
    quote_applicable: bool,
    quote_match_ratio: float,
    quote_source_in_topk: bool,
    negation_consistent: bool,
    category_consistent: bool,
    source_chunk_id: uuid.UUID | None,
) -> StateUpdate:
    """Every check's outcome as a state update. No defaults on purpose: every
    path must state each check explicitly."""

    return {
        "schema_valid": schema_valid,
        "quote_applicable": quote_applicable,
        "quote_match_ratio": quote_match_ratio,
        "quote_source_in_topk": quote_source_in_topk,
        "negation_consistent": negation_consistent,
        "category_consistent": category_consistent,
        "source_chunk_id": source_chunk_id,
    }


ALL_FAILED = _checks(
    schema_valid=False,
    quote_applicable=False,
    quote_match_ratio=0.0,
    quote_source_in_topk=False,
    negation_consistent=False,
    category_consistent=False,
    source_chunk_id=None,
)


class ValidateNode(BaseNode):
    def __call__(self, state: TriageState) -> StateUpdate:
        proposal = state.proposal
        reranked = state.reranked

        if proposal is None:
            return ALL_FAILED

        if not isinstance(proposal.root, AutoReplyProposal):
            return _checks(
                schema_valid=True,
                quote_applicable=False,
                quote_match_ratio=0.0,
                quote_source_in_topk=False,
                negation_consistent=True,
                category_consistent=True,  # checked by core-api's router against KB category
                source_chunk_id=None,
            )

        quote = normalize_ws(proposal.root.verbatim_quote)
        topk = {c.chunk_id: normalize_ws(c.content) for c in reranked}

        # 1. Exact substring first.
        source = next((cid for cid, txt in topk.items() if quote in txt), None)
        ratio = 1.0 if source else 0.0

        # 2. Fuzzy ONLY to catch whitespace/punctuation drift, at >= threshold.
        if source is None:
            cid, ratio = _best_fuzzy(quote, topk)
            source = cid if ratio >= settings.quote_fuzzy_threshold else None
            if source is None:
                ratio = 0.0 if cid is None else ratio

        # 3. Source must be in the retrieved top-k.
        in_topk = source is not None

        # 4. Negation check — fuzzy match cannot catch this.
        raw = {c.chunk_id: c.content for c in reranked}
        neg_ok = (
            _negations_in(quote, NEGATIONS)
            == _negations_in(_enclosing_sentences(quote, raw[source]), NEGATIONS)
            if source is not None
            else False
        )

        return _checks(
            schema_valid=True,
            quote_applicable=True,
            quote_match_ratio=ratio,
            quote_source_in_topk=in_topk,
            negation_consistent=neg_ok,
            category_consistent=True,
            source_chunk_id=source,
        )


validate = ValidateNode()
