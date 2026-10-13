# ADR-0022: The drafted answer runs on DeepSeek in production

**Status:** Proposed
**Date:** 2026-10-12
**Supersedes:** ADR-0019 for the drafted answer only: DeepSeek is no longer
evaluation-only for the draft. ADR-0019 stands for the proposal, PII NER and
the entity-graph build.
**Builds on:** ADR-0021 (the drafted answer steers retrieval)

## Context

The drafted answer (ADR-0021) decides which pages and chunks retrieval looks
at. On the 500-ticket set with the entity graph, drafting on DeepSeek scores
recall@3 0.866 against 0.816 drafting on the local Qwen3-8B
(`evals/HISTORY.md` 2026-10-12 (2), (4)): Qwen's smaller drafts name the
wrong feature or invent detail more often ((3)).

## Decision

1. **Production drafts on DeepSeek:** `DRAFT_CLIENT_PROVIDER=deepseek` in a
   deployment's `.env`. The draft call sends the **masked** ticket (subject
   and body after core-api's masking), the same text Jev's hosted API
   already receives (ADR-0015). Raw text never leaves: PII NER stays local
   (`NER_CLIENT_PROVIDER=vllm`, ADR-0019).
2. **The template ships `vllm`.** The DeepSeek client refuses to build
   without a key, and the template ships none: a template defaulting to
   `deepseek` would stop `cp .env.example .env`, and CI, from booting.
3. Nothing else changes: the draft is still never shown, quoted or scored,
   and a failed draft is a 500 → HITL (ADR-0021).

## Consequences

- One more third party sees masked ticket text, alongside Jev.
- DeepSeek's draft is not repeatable at temperature 0, and about 1 in 350
  drafts is malformed JSON (a ticket for a person): `evals/HISTORY.md`
  2026-10-11 (5).
- Every ticket's retrieval now depends on DeepSeek's availability: an
  outage sends every ticket to a person.
- The circularity caveat of the measurements: the 440 drafted golden tickets
  were themselves written by DeepSeek; on the 60 hand-authored tickets
  DeepSeek and Qwen drafting both score 0.917.
