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
   English quote. Negations are counted, not just collected: "Do not X if
   you do not have Y" quoted as "X if you do not have Y" keeps one "not"
   and drops the one that governs it.

   Known gap: a list item is its own sentence, so "Don't do any of the
   following:" does not reach a quote cut from an item below it
   (test_validate.py pins this as an xfail).
"""

from __future__ import annotations

from typing import Any

import re
import uuid
from collections import Counter

from rapidfuzz import fuzz

from ai_engine.graph.nodes.infer.proposals import AutoReplyProposal, ClarificationProposal
from ai_engine.graph.state import TriageState

from ai_engine.core.config import settings
from ai_engine.graph.build.node import BaseNode

NEGATIONS = {"không", "chưa", "ngoại trừ", "trừ khi", "không được", "cấm"}
ENGLISH_NEGATION = re.compile(
    r"\b(?:not|no|never|cannot|none|nor|without|except|unless)\b|\b\w+n['’]t\b",
    re.IGNORECASE,
)
_ABBREVIATIONS = ("e.g", "i.e", "etc", "vs")
_SENTENCE_BREAK = re.compile(
    "".join(rf"(?<!\b{re.escape(abbr)})" for abbr in _ABBREVIATIONS) + r"[.!?](?=\s)|\n",
    re.IGNORECASE,
)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _negations_in(text: str) -> Counter[str]:
    """Each negation in `text` with how many times it occurs. A count, not a
    set: a set can't tell a quote that kept one of two "not"s from the
    sentence that had both."""

    lowered = text.lower()
    found = Counter({neg: lowered.count(neg) for neg in NEGATIONS if neg in lowered})
    found.update(m.group(0).lower().replace("’", "'") for m in ENGLISH_NEGATION.finditer(text))
    return found


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


def _clarify_options_shown(state: TriageState) -> bool:
    """A clarify proposal's options are two or more distinct slugs of the
    chunks the model was shown (ADR-0016). A question choosing between pages
    it never saw, or between one page and itself, is not a real choice."""

    proposal = state.proposal.root if state.proposal else None
    if not isinstance(proposal, ClarificationProposal):
        return False
    options = set(proposal.proposed_options)
    return len(options) >= 2 and options <= {c.article_slug for c in state.reranked}


class ValidateNode(BaseNode):
    """Every exit returns all five checks. A check left out would not fail
    loudly: it reads as its "failed" state default, so a deliberate pass
    (negation on a route proposal) would silently lower trust.
    test_validate.py pins each exit's whole update."""

    def __call__(self, state: TriageState) -> dict[str, Any]:
        if state.proposal is None:
            return {
                "quote_applicable": False,
                "quote_match_ratio": 0.0,
                "quote_source_in_topk": False,
                "negation_consistent": False,
                "clarify_options_in_topk": False,
            }

        if not isinstance(state.proposal.root, AutoReplyProposal):
            return {
                "quote_applicable": False,
                "quote_match_ratio": 0.0,
                "quote_source_in_topk": False,
                "negation_consistent": True,
                "clarify_options_in_topk": _clarify_options_shown(state),
            }

        quote = normalize_ws(state.proposal.root.verbatim_quote)
        topk = {c.chunk_id: normalize_ws(c.content) for c in state.reranked}

        # 1. Exact substring first.
        source = next((cid for cid, txt in topk.items() if quote in txt), None)
        ratio = 1.0 if source else 0.0

        # 2. Fuzzy ONLY to catch whitespace/punctuation drift, at >= threshold.
        if source is None:
            cid, ratio = _best_fuzzy(quote, topk)
            source = cid if ratio >= settings.quote_fuzzy_threshold else None

        # 3. Source must be in the retrieved top-k.
        in_topk = source is not None

        # 4. Negation check — fuzzy match cannot catch this. Against the raw
        # chunk, whose line breaks still mark list items.
        neg_ok = source is not None and _negations_in(quote) == _negations_in(
            _enclosing_sentences(
                quote, next(c.content for c in state.reranked if c.chunk_id == source)
            )
        )

        return {
            "quote_applicable": True,
            "quote_match_ratio": ratio,
            "quote_source_in_topk": in_topk,
            "negation_consistent": neg_ok,
            "clarify_options_in_topk": False,
        }


validate = ValidateNode()
