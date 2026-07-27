# ADR-0003: `llm_self_confidence` is excluded from routing and from the trust score

**Status:** Accepted
**Date:** 2026-07-27

## Context

Every LLM proposal carries `self_confidence: float` (0-100). It is
tempting to use it — it's already there, it's cheap, and intuitively a
model that says "95% confident" ought to be more trustworthy than one that
says "40% confident". This is the ADR that will be pointed to when someone
asks "why aren't we using the confidence score the model gives us?".

## Decision

`llm_self_confidence` is logged (`ai_runs.llm_self_confidence`,
`TrustSignals.llm_self_confidence`) for later analysis, and is explicitly
**excluded** from:

1. `trust_scorer.FEATURES` (see the comment in
   `services/core-api/apps/tickets/services/trust_scorer.py`), and
2. `router.route()` — no branch decision reads it.

`TrustScore` is instead built entirely from *externally verifiable*
signals: retrieval scores, whether the quoted text actually exists in the
retrieved chunk, whether a negation was flipped, whether the KB category
matches the proposed category. All of these can be checked by code without
trusting the model's own report of its correctness.

## Rationale (counterintuitive, so it needs evidence)

LLM self-reported confidence is known to be poorly calibrated, and worse,
it is trivially gameable by prompt/model changes without any actual gain in
accuracy — a model can be tuned to simply *say* "95%" more often. A trust
score built on top of that number inherits its miscalibration invisibly.

Spec §7.2 requires monthly comparison of `llm_self_confidence` against
actual outcomes specifically so this decision rests on this domain's own
data rather than a general claim. After a few months of shadow-mode data,
this ADR should be revisited with that evidence attached — but the
correlation would need to be strong and stable before self-confidence
re-enters the score, not merely "better than random."

## Consequences

- The trust score is slightly more expensive to compute (multiple
  verifiable signals instead of one number the model already handed us).
- The trust score cannot be improved by a model that has simply learned to
  sound more confident.
