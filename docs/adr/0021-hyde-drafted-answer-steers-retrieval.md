# ADR-0021: A drafted answer steers retrieval (HyDE)

**Status:** Proposed
**Date:** 2026-10-11
**Builds on:** ADR-0020 (no BM25 on the ticket), ADR-0014 / ADR-0018 (link
expansion), ADR-0015 (Jev reranks)
**Touches:** ADR-0005 (what may be thresholded), ADR-0019 (DeepSeek for
evaluation only), CLAUDE.md's organizing principle (the LLM proposes)

## Context

A ticket describes symptoms in the requester's words ("our emails arrive
unsigned"); the page that fixes it names features, settings and commands
("Enabling S/MIME signing on a configuration set"). Retrieval on the ticket
alone found the gold page among its 10 candidate pages for 76% of the 500
`kb_covered` tickets, and recall@3 was 0.736 (local replay, 2026-10-11).

## Decision

1. **`DraftAnswerNode` runs after the injection guard, before retrieval.**
   The triage chat model (`CHAT_CLIENT_PROVIDER`) writes, from the masked
   ticket, the documentation passage it expects would answer it
   (`core/prompts/hyde_draft.v1.md`, `DRAFT_TEMPERATURE` 0), and the
   embedder embeds it.
2. **Retrieval fuses three ranked lists:** vector search on the ticket, BM25
   on the draft, vector search on the draft; then the first
   `FUSION_CANDIDATE_LIMIT` pages, one chunk each.
3. **Each candidate page brings its best-fused chunk and its
   `DRAFT_CHUNKS_PER_PAGE` (2) chunks nearest the draft;** link expansion
   takes linked pages' chunks nearest the draft.
4. **The ticket, never the draft, is scored:** the cross-encoder and Jev
   score chunks against the masked ticket, and only Jev's score meets a
   threshold (ADR-0005). The ticket's own embedding stays the one few-shot
   selection reads.
5. **The draft is discarded.** It is never shown, quoted, validated or sent
   to core-api; it is not a proposal and carries no `proposed_` field.
6. **A failed draft fails the run:** a chat error, a reply that is not JSON,
   or an empty draft raises, so the ticket goes to a person as
   `ai_engine_unavailable` (rule 3). There is no fallback to ticket-only
   retrieval, which would quietly run the weaker pipeline.

## Rationale

Measured by local replay on the 500 `kb_covered` tickets, authored links,
DeepSeek drafts (`evals/HISTORY.md` 2026-10-11):

| | Gold page among 10 candidates | Recall@3 | Strict |
|---|---|---|---|
| Ticket only | 76% | 0.736 | 0.674 |
| This design | 94% | **0.858** | **0.812** |

Variants measured and not taken: three drafts per ticket (0.850, trades
tickets rather than adding), the cross-encoder scoring against the draft
(0.816), a mixed shortlist by ticket and by draft (0.866, a tie at a second
cross-encoder pass), Jev's shortlist at 20 (0.864, a tie at a third more Jev
calls).

## Consequences

- One more model call per ticket, before retrieval: latency and, on a cloud
  provider, cost. Its tokens are not yet added to the run's `tokens_in` /
  `cost_usd`.
- **The drafting model is the triage chat model.** Every number above is
  from DeepSeek drafts. With `CHAT_CLIENT_PROVIDER=deepseek` the ticket goes
  to DeepSeek, which ADR-0019 allows for evaluation only; production's
  default is the local Qwen, whose drafting is unmeasured. Shipping beyond
  evaluation needs Qwen measured, or a decision superseding ADR-0019.
- When the draft names the best-known feature instead of the one the ticket
  describes (DKIM for an S/MIME ticket), retrieval follows it; about 20 of
  the design's 71 misses are of that kind.
- A prompt change is eval-gated like `PROMPT_VERSION`.
