# ADR-0017: Jev chooses the ticket's category; the LLM's category is log-only

**Status:** Proposed. Supported by a probe on the golden set; not built.
**Date:** 2026-10-04
**Builds on:** ADR-0001 (code decides, the LLM proposes), ADR-0015 (Jev, the
reranker), ADR-0016 (the direction: the LLM writes, it doesn't decide)
**Touches:** ADR-0002 (KB metadata as authority), spec §8 (routing)

## Context

The ticket's category decides where an auto-routed ticket goes and is
stored on `tickets.category`. Today the classify LLM proposes it as part of
its proposal, and the router takes it as given. On 2026-10-04 that LLM
failed in ways a category doesn't need to: replies longer than its 4,096-token
context returned nothing (`all_llm_down`), and malformed replies put
"security" in `proposed_intent`. Its category F1 for `security` (0.82-0.89)
was the gate that failed most often that day.

Jev, the hosted model that already reranks every ticket's pages, answers
structured questions about a state: a `noul` (is this true, 0-1), a `score`,
or a `choice` among named options with a probability per option and a
confidence. A probe compared it with the LLM on the classification suite's
83 tickets (`evals/HISTORY.md`, 2026-10-04 (5)):

| Classifier | Correct (of 83), 2 passes |
|---|---|
| LLM, `classify.v7` | 77 · 78 |
| Jev, six yes/no questions | 77 · 75, fails the F1 floor |
| Jev, one choice question | 77 · 77, fails the floor |
| **Jev, one choice question + the answering page's title** | **80 · 79, every category ≥ 0.89** |
| Jev, the same + the page's chunk text | 77 · 77, fails the floor |

Separate yes/no questions can't weigh one category against another, and
follow words ("permission denied" → `access`). One choice question compares.
The page tells Jev what the ticket is about, as the retrieved excerpts tell
the LLM; the page's *text* pulls it the other way, because how to fix a
problem names other categories' parts.

## Decision

**Jev chooses the category; the router takes its choice.**

1. **ai-engine asks one `choice` question per ticket**, after reranking: the
   six categories as options, each described by the classify prompt's
   definition, verbatim. The state is the masked ticket and, when a page is
   above the retrieval floor, `{"title": <the top page's title>}`; out-of-KB
   tickets get no page. The question is a versioned file beside
   `rerank_resolves.v1.json` (`category.v1.json`), loaded at boot.
2. **The wire schema carries Jev's answer**, in both services:
   `category_choice` (a `TicketCategory` or none) and `category_confidence`
   (0-1), defaulted for stored rows.
3. **`router.py` decides with it.** The ticket's category, for `auto_route`
   and for `tickets.category`, is Jev's choice. Below
   `classification.min_confidence` (🔧 `thresholds.yaml`), or with no choice
   at all, the ticket goes to a human under a new `ReasonCode`,
   `category_low_confidence`. The LLM's `proposed_category` is kept in the
   proposal and logged, and decides nothing.
4. **A Jev failure raises**, as in the rerank node: ai-engine answers 500 and
   core-api sends the ticket to a human as `ai_engine_unavailable`. No
   fallback to the LLM's category: a silent switch of classifier would hide
   the outage and change the calibration under the threshold.

## Consequences

- One more Jev call per ticket, after reranking (~0.25 s in the probe).
  Jev's API failed three times on 2026-10-04 (a TLS error, two 520s); each
  failure is now also a lost category, so a ticket for a human.
- The category no longer depends on the LLM's context window or on its
  output format. The intent (answer, route, ask, refuse) still does, until
  the router decides that too.
- `min_confidence` needs calibrating on shadow data. In the probe,
  confidence below 0.65 caught 2 of 3-4 misses for 2 correct tickets.
- The classification suite measures Jev's choice instead of the LLM's.
- `category_consistent` (the LLM's category against the KB page's) loses its
  meaning for route proposals and needs re-deciding.

## Not decided

- The intent. Moving it into the router (from Jev's `resolves`, multi-issue
  and underspecified scores) is the next stage, its own ADR.
- `multi_issue` as a router gate: Jev's noul separated the 18 multi-issue
  golden tickets perfectly (AUROC 1.00), a separate decision.
- g042's conflict: "not authorized to perform lambda:InvokeFunction" is
  `access` by the written definition and `software` by its golden label.

## Alternatives

- **Keep the LLM's category.** It passes the floor, but its misses are
  failures of the call (overflow, format), not judgement, and they land on
  `security`.
- **Jev's six yes/no scores**, with or without the definitions: fails the
  floor; follows words.
- **A router check that sends Jev/page-category disagreement to a human**
  (simulated in the probe): no unflagged errors, but more human work, and
  Jev's errors were not fewer, only caught. The page as Jev's context fixes
  the errors instead.
- **The page's chunk text as context**: worse than the title (above).

## Before this is accepted

- Re-measure on tickets the question was not written against (shadow data,
  or a held-out set).
- A full eval run with it built, including the end-to-end suite.
