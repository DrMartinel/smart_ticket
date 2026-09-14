"""
Validator — spec §6.4. Implements the four checks in the exact order the
spec gives, because the order encodes why each one exists:

1. Exact substring match first — cheap, unambiguous.
2. Fuzzy match ONLY as a narrow allowance for whitespace/punctuation
   drift, gated at 0.95 — not a general "close enough" check.
3. The quote's source chunk MUST be one of the retrieved top-k. A quote
   that is verbatim-correct but pulled from the WRONG KB article is a
   wrong answer with a misleadingly high string-similarity score.
4. Negation check — the one fuzzy matching cannot catch. "được cấp
   quyền" vs "không được cấp quyền" score ~0.96 similarity while meaning
   the opposite thing. This is the single highest-value check added
   after the v1 architecture review, and it exists specifically because
   of how common negated conditions are in ITSM runbook-style KB content.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from contracts.llm_draft import AutoReplyProposal

from ai_engine.graph.state import TriageState, ValidationResult

# A Vietnamese linguistic lexicon, not a tunable number — it belongs in code
# for the same reason patterns.py holds the PII regexes. Constructor-visible
# so a test can narrow it, not so deployments can diverge.
DEFAULT_NEGATIONS = {"không", "chưa", "ngoại trừ", "trừ khi", "không được", "cấm"}


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _negations_in(text: str, negations: set[str]) -> frozenset[str]:
    lowered = text.lower()
    return frozenset(neg for neg in negations if neg in lowered)


def _best_fuzzy(quote: str, topk: dict[int, str]) -> tuple[int | None, float]:
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


class ValidateNode:
    """Read-only after __init__; one instance is shared across FastAPI's
    threadpool."""

    def __init__(self, *, fuzzy_threshold: float, negations: set[str] | None = None) -> None:
        # No default: the value lives in Settings, and a constructor default
        # duplicating it would be a second source of truth for one tunable.
        self._fuzzy_threshold = fuzzy_threshold
        self._negations = negations if negations is not None else DEFAULT_NEGATIONS

    def __call__(self, state: TriageState) -> dict:
        proposal = state.get("proposal")
        reranked = state.get("reranked", [])

        if proposal is None:
            result: ValidationResult = {
                "schema_valid": False,
                "quote_applicable": False,
                "quote_match_ratio": 0.0,
                "quote_source_in_topk": False,
                "negation_consistent": False,
                "category_consistent": False,
            }
            # `iteration` is bumped ONLY here. TriageState has no reducer on
            # it, so hoisting this to the top of the method would make every
            # successful pass increment too and silently shift the
            # `iteration < 2` retry cap in build.py.
            return {"validation": result, "iteration": state["iteration"] + 1}

        if not isinstance(proposal.root, AutoReplyProposal):
            result = {
                "schema_valid": True,
                "quote_applicable": False,
                "quote_match_ratio": 0.0,
                "quote_source_in_topk": False,
                "negation_consistent": True,
                "category_consistent": True,  # checked by core-api's router against KB category
            }
            return {"validation": result}

        quote = normalize_ws(proposal.root.verbatim_quote)
        topk = {c.chunk_id: normalize_ws(c.content) for c in reranked}

        # 1. Exact substring first.
        source = next((cid for cid, txt in topk.items() if quote in txt), None)
        ratio = 1.0 if source else 0.0

        # 2. Fuzzy ONLY to catch whitespace/punctuation drift, at >= threshold.
        if source is None:
            cid, ratio = _best_fuzzy(quote, topk)
            source = cid if ratio >= self._fuzzy_threshold else None
            if source is None:
                ratio = 0.0 if cid is None else ratio

        # 3. Source must be in the retrieved top-k.
        in_topk = source is not None

        # 4. Negation check — fuzzy match cannot catch this.
        neg_ok = (
            _negations_in(quote, self._negations)
            == _negations_in(topk.get(source, ""), self._negations)
            if in_topk
            else False
        )

        result = {
            "schema_valid": True,
            "quote_applicable": True,
            "quote_match_ratio": ratio,
            "quote_source_in_topk": in_topk,
            "negation_consistent": neg_ok,
            "category_consistent": True,
        }
        if source is not None:
            result["source_chunk_id"] = source

        return {"validation": result}
