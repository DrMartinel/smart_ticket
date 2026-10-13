# ADR-0024: The drafted answer is grounded in the KB's pages

**Status:** Rejected for now (2026-10-12): built, probed, reverted. No
measured gain on this KB; kept as the record for a KB the draft model
doesn't know. `hyde_draft.v2.md` stays in `core/prompts/`, unused.
**Date:** 2026-10-12
**Amends:** ADR-0021 (the drafted answer steers retrieval): what the draft
model is shown. Retrieval, scoring and failure handling are unchanged.
**Touches:** ADR-0023 (the clarifying question's options come from the
pages retrieval finds), ADR-0005

## Context

Under ADR-0021 the draft model wrote the passage it expected would answer
the ticket from the ticket alone, out of what it knew of the topic. Two
problems followed:

1. **An ambiguous ticket drafted one reading at random.** `hyde_draft.v1`
   said "if unsure, write the most likely relevant documentation passage".
   "I forgot my password, how do I reset it?" drafted the AWS access portal
   one run and WorkSpaces the next (DeepSeek is not repeatable at
   temperature 0). Retrieval follows the draft, so the WorkSpaces page was
   in Jev's top 5 in 4 of 6 runs, and the clarifying question's options
   changed with it (2026-10-12, TKT-2026-000019 to -000024).
2. **The draft depends on the model knowing the topic.** It works on this
   demo KB because the KB is public AWS documentation the model was trained
   on. On a company's own wiki (internal application names, "the Finance
   portal password") the model knows none of the vocabulary, and its draft
   would be generic or invented. The +10 points HyDE measured are partly
   "DeepSeek knows AWS".

Telling the model to cover every reading would fix (1) only by asking it to
guess which systems exist, inventing some and missing others.

## Decision

**The draft model is shown the KB's pages nearest the ticket**, a form of
pseudo-relevance feedback:

1. `DraftAnswerNode` embeds the ticket (moved from retrieval, which now
   reuses it) and runs the vector search on it.
2. The first `DRAFT_CONTEXT_PAGES` (10) distinct active pages, nearest
   first, are listed under the ticket as "title — heading", the heading
   being the one the page's nearest chunk starts with ("Getting started
   with your WorkSpace — (Optional) Change your password").
3. `hyde_draft.v2` writes in those pages' terms, names no product or system
   that neither the ticket nor the list names, and, when the ticket could
   concern several of the listed systems, writes one short passage per
   reading (at most 3) instead of picking one.

The vector search's similarity only orders the list; nothing is compared
with it (ADR-0005). A KB read that fails fails the draft (500 → HITL):
drafting without the pages would quietly run the ungrounded pipeline
(rule 3). An empty result is not a failure: the draft is written with
"(no pages found)", and the retrieval floor sends the ticket to a person.

## Consequences

- The systems a draft may cover are the ones the loaded KB has near the
  ticket, read from the KB at request time: the same code serves another KB
  without a prompt naming its products.
- One more vector search per ticket, before the draft (milliseconds), and
  about ten lines more in the draft prompt. The ticket is embedded once
  instead of twice.
- When the ticket-only search misses the right area (before HyDE, 24% of
  tickets had no gold page among the 10 candidate pages), the list points
  the draft the wrong way. The model may still use its own knowledge for
  the content, so it should do no worse than v1 on a public topic; that is
  to be measured.
- **Not yet measured:** recall@5 on the 500-ticket set (gate ≥ 0.90; v1
  measured 0.912), and whether the options of a clarifying question stop
  changing between runs (a probe of the password ticket and g151-g156).
- HyDE cannot yet be switched off for a KB where drafting doesn't help;
  that is a separate decision, superseding part of ADR-0021.

## Outcome (2026-10-12)

Built (`hyde_draft.v2`, `DRAFT_CONTEXT_PAGES=10`) and probed in-process on
23 runs: "I forgot my password, how do I reset it?" ×5 and g151-g156 ×3
(`~/.cache/smart-ticket-lightrag/probe/clarify_v2.jsonl`), then reverted.

| Password ticket | v1 (6 live runs) | v2 (5 runs) |
|---|---|---|
| Distinct top-5 page sets | 3 | 3 |
| WorkSpaces page in the top 5 | 4 of 6 | 3 of 5 |
| Distinct option sets offered | 5 | 5 |

- **Consistency did not improve.** Most of the variation is the proposal
  model choosing different options from an identical top 5 (password runs
  2-3, all three g154 runs); on g153, g154 and g156 it also switched between
  `clarify` and `insufficient_context`. A draft change cannot reach that.
- **Retrieval varied as before:** the 5th slot swaps between near-ties, and
  2 of 5 password drafts still left WorkSpaces out.
- **Recall was not measured** (no 500-ticket run). On public AWS
  documentation the model already knows the vocabulary, so the page list
  was not expected to add much here; the case for v2 is a KB the model
  wasn't trained on, which this project can't test.

Next tried instead: Doc2Query-- (questions generated from each chunk at
index time and filtered by the cross-encoder), as an offline probe.
