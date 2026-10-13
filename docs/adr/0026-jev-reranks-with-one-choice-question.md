# ADR-0026: Jev reranks with one choice question, and an auto-reply must cite Jev's choice

**Status:** Proposed (2026-10-13), the owner's decision; not yet eval-gated
**Date:** 2026-10-13
**Supersedes:** ADR-0015 decision 2 (one noul question per chunk) and its
"Why a noul, not a `score` or `choice`" section. ADR-0015's other
decisions stand: two stages, thresholds read Jev's score only, a Jev
failure fails the run, only masked text leaves the host.
**Builds on:** ADR-0005 (thresholds compare one reranker's score), ADR-0017
(Jev's choice question for the category, on the same client)

## Context

The 2026-10-13 shadow calibration run (532 AI-reviewed tickets from the
golden set) could not set `t_auto`: a fitted trust model barely beat
guessing (test accuracy 0.57 against 0.55), and wrong auto-reply proposals
scored as high as right ones. Most of the wrong pages (49 of 74) came from
the LLM citing a page that was not Jev's #1, while every trust feature
(`rerank_top1`, `rerank_margin`) reads Jev's #1, not the cited page. No
signal said whether the page the answer cites is the one the reranker
believed in.

A noul judges each passage alone, so 15 independent probabilities give no
measure of how sure Jev is that one page, rather than several, fixes the
ticket. A choice question sees every passage at once and returns a
probability per option and a confidence.

The probe (2026-10-13, scratchpad, not a gate run) asked one choice
question over the same 15-chunk shortlists as production, on the 420
golden tickets whose pipeline reached the reranker, against the shipped
noul on the same pools:

| | noul (`rerank_resolves.v1`) | choice (`rerank_choice.v1`) |
|---|---|---|
| recall@1 | 0.736 | 0.771 |
| recall@3 | 0.900 | 0.912 |
| recall@5 | 0.919 | 0.929 (ceiling 0.936: the gold page in the shortlist) |
| #1 right when sure (top score ≥ 0.9 / confidence ≥ 0.9) | 86.0% | 93.3% |

65% of the choice's ranks 2–5 have probability < 0.01: below its choice,
Jev's probabilities mostly tie and the cross-encoder's order breaks the
tie. Jev chose `none` 6 times.

Jev's choice agreeing with the page the LLM cited, at confidence ≥ 0.9,
held for 193 of 423 auto-reply proposals, 96.4% of them on the right page.

## Decision

1. **One choice question per ticket over the shortlist**,
   `core/prompts/rerank_choice.v1.json` (`RERANK_PROMPT_VERSION`). The
   options are `c1`…`cN`, one per shortlisted passage (described by its
   page title, from the file's `passage_option`), plus `none`. The state is
   `{ticket: {subject, body}, passages: {cN: {title, text}}}`. The noul
   question file stays, unused; `JevClient.ask` and the noul reply type are
   removed.
2. **`rerank_score` is the passage's choice probability.** Jev's order is
   final; equal probabilities keep the cross-encoder's order (a stable
   sort). A reply that leaves out any option's probability, or adds one,
   raises: a missing passage is not a zero.
3. **Jev choosing `none` is below the floor**: refuse-before-LLM, whatever
   the top probability. `ClassifyCategoryNode` asks Jev's category with no
   page, and `RetrievalSignals.rerank_chose_none` sends the ticket to a
   human as `retrieval_below_floor`, not `schema_invalid`.
4. **An auto-reply must cite Jev's choice, chosen with confidence.**
   ai-engine reports `RetrievalSignals.rerank_confidence` and
   `GenerationSignals.cited_is_rerank_choice` (the auto-reply's `kb_slug`,
   and the page of the chunk its quote was found in, are the chosen
   passage's page). The router sends an auto-reply proposal
   that fails either to a human, after the quote checks and before trust:
   `rerank_disagrees`, then `rerank_low_confidence` below
   `retrieval.min_rerank_confidence` (0.9 🔧). Both signals default to
   their failing value, so a run that never reported them cannot
   auto-reply.

## Consequences

- **Every Jev-scale number is now on the wrong scale.** `retrieval.floor`
  (0.30), `retrieval.margin` (0.08), `clarification.option_margin` (0.1),
  the trust coefficients and the eval baselines were set on noul scores.
  Choice probabilities sum to 1 over the shortlist, so the top-1 runs lower
  when Jev is split and the margin much wider when it is not. All must be
  re-chosen; the owner deferred the eval run and the recalibration.
- **Fewer auto-replies.** On the probe, the agreement check passes 193 of
  423 auto-reply proposals before trust is read.
- **One request per ticket** instead of 15, each carrying the whole
  shortlist. Latency and cost were not measured.
- **Options are chunks, not pages.** Two chunks of the right page in the
  shortlist split Jev's probability, which can put a clear page below
  `min_rerank_confidence`. It fails toward a human, and the probe measured
  this shape; one option per page is a candidate for the eval run.
- **`several` is not an option.** A probe of a "one / several / none"
  question on 96 tickets said `several` on 37 of 60 clear tickets, so
  choosing clarify options from it was dropped for now.

## Open before acceptance

- A full eval run with `rerank_choice.v1`, and the floor, margins and
  `min_rerank_confidence` re-chosen on its data (a reviewer other than the
  author for any baseline change).
- Repeatability of the choice's probabilities across runs.
- Prompt injection through the passages, as ADR-0015 left open.

## Alternatives

- **Keep the noul and add the agreement check on Jev's #1.** The noul's
  confidence signal is weaker (86.0% against 93.3% at ≥ 0.9).
- **Ask the choice beside the nouls** (16 requests): two scales for one
  stage, and the noul's order is worse.
- **A `several` option** (above).
