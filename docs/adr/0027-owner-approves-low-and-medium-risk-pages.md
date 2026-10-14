# ADR-0027: The owner approves every low- and medium-risk demo KB page for auto-reply

**Status:** Accepted (2026-10-14), the owner's decision of 2026-10-12, recorded after the fact
**Date:** 2026-10-14
**Departs from:** spec §14 P4 ("auto-reply on 3–5 `risk_tier=low` KB articles") and the rule `load_demo_kb` enforced for it (only `low` may be approved)
**Builds on:** ADR-0002 (auto-reply authority lives on KB rows, set by a named manager with a reason)

**This relaxes a guardrail.** Before, at most a handful of reviewed low-risk
pages could be approved, and the loader refused anything above `low`. After
this ADR, every low- and medium-risk page of the demo KB is approved, and the
loader accepts `low` and `medium`. `high` (security and `other`) is still
refused, and still needs a person's review page by page.

## Context

On 2026-10-12 the owner approved every active low- and medium-risk page for
auto-reply: 2,887 pages in one bulk change through
`KbArticle.set_auto_reply_allowed`, each writing a `kb_authority_log` row
("bulk approval of every low- and medium-risk page, requested by the project
owner; high-risk pages left for review"). With the 5 earlier approvals,
2,892 of 3,542 pages are approved. The purpose was the shadow pilot: the
router should decide on the pages a real deployment would allow, so the
shadow data says what auto-reply would do.

The approval was never written to `demo_kb/curation.json`. That file is what
`load_demo_kb` applies and what the golden set takes its labels from, so the
two disagreed: a re-run of the loader would not reproduce the database, and
the end-to-end suite scored every auto-reply on a medium-risk page as wrong
(g006 and g014 in the 2026-10-14 sample run).

## Decision

1. **`curation.json` records the approval.** Every approved page has an
   `auto_reply` entry pinned to its manifest SHA-256, with the bulk reason.
   A changed page is still not applied and an existing approval revoked.
2. **The loader accepts low and medium.** A page's tier is its own
   `risk_tiers` entry, else its category's default. A `high` page, or an
   approval for a page the snapshot doesn't list, is refused before
   anything loads.
3. **The golden set follows `curation.json`, as before.** 402 labels change
   from `hitl` (`kb_not_authorized`) to `auto_reply`, among them 359 drafted
   and 25 authored KB-covered tickets. The six near-miss tickets (g169–g174)
   now take their answering page's branch; an auto-reply citing the page
   they resemble is still wrong. IDs and texts don't change.

## Consequences

- **Auto-reply precision now measures most of the KB.** It was measured on
  the 5 approved pages; it now covers 445 tickets expecting `auto_reply`.
  The baseline comparison changes meaning, and a baseline update needs a
  reviewer other than the author (CLAUDE.md rule 9).
- **No live auto-reply yet.** `SHADOW_MODE=true`: the router records its
  decisions and a person handles every ticket. Turning shadow mode off is
  P4's step, and spec §14 question 6 (who is responsible when an auto-reply
  is wrong) must be answered in writing first.
- The other gates still apply to every approved page: the quote checks,
  Jev's choice at confidence ≥ 0.9 (ADR-0026) and trust ≥ `t_auto`.

## Alternatives

- **Keep the golden labels on 5 pages.** The gate would keep failing on
  tickets that behave as the owner intends.
- **Revoke the bulk approval.** The pilot's shadow data would then say
  nothing about auto-reply on most of the KB.
