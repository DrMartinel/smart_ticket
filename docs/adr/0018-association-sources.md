# ADR-0018: Association sources for link expansion, built at ingest time and offline

**Status:** Proposed. Built in phases 1-4 of the LightRAG associations plan;
the parity check, the spike check, the full build and the eval runs
(*Before this is accepted*) have not run.
**Date:** 2026-10-07
**Builds on:** ADR-0014 decision 1 (an article-associations layer feeds
candidate expansion) and its *Before this is accepted* #3 (a KB-agnostic
association source)
**Touches:** ADR-0004 (ai-engine's read-only role: one more SELECT grant),
ADR-0002 (auto-reply quotes approved KB text only), ADR-0005 / ADR-0015 (which
score a threshold may see), ADR-0012 (ai-engine is the only vLLM client)

## Context

Link expansion (ADR-0014) follows the Markdown links of the articles behind
the cross-encoder's top 3 chunks, and on the demo KB that recovers misses
nothing else does. It has two limits:

1. **It only works on a KB that links its pages.** An internal KB of
   hand-written runbooks often has no links at all.
2. **It extracts links per request**, regex over every seed's chunk text on
   every ticket, because there was no table to read them from.

ADR-0014 named the fix for both: an associations table core-api writes at
ingestion, tagged by `source`, which `linked_article_ids()` reads without
changing its contract; and, measured against `authored_link` with the links
withheld, two KB-agnostic sources: embedding neighbours between articles (no
LLM), then per-article entity extraction.

## Decision (proposed)

**1. `kb_article_associations` holds every association, tagged by source.**
core-api owns the table (`source_article`, `target_article`, `source`,
`score`, `evidence`, `reviewed`, `build_id`). `score` is comparable only
within one source and only orders one seed's targets; it never reaches a
threshold, the trust score or the router. `ai_engine_ro` gets SELECT on it
(`infra/migrations/sql/0006_association_grant.sql`), and nothing else.

**2. Rows are stored for inactive targets too; the read hides them.**
`linked_article_ids()` joins `kb_articles.is_active`, so deactivating or
reactivating an article takes effect on the next ticket with no rebuild.

**3. Three sources; a deployment follows exactly one, `ASSOCIATION_SOURCE`**
(`authored_link`, `embedding_neighbour`, `entity_graph`, or `none` to turn
expansion off). Sources are compared against each other, not fused: their
scores are on different scales, and combining them would need its own rule
and its own evaluation.

| Source | Built by | Model calls |
|---|---|---|
| `authored_link` | core-api, at ingest and by `build_associations --source authored_link` | none |
| `embedding_neighbour` | core-api `build_associations --source embedding_neighbour`, cosine between article centroids of stored chunk vectors | none |
| `entity_graph` | ai-engine's offline build job (LightRAG), scored and loaded by core-api | offline only, never per ticket |

**4. The entity extractor runs offline only, and only its entities survive.**
LightRAG (`lightrag-hku`, pinned, in a `build` dependency group the served
image doesn't install) extracts entities per article through ai-engine's own
chat settings and embedder (ADR-0012). Its summaries, relationship
descriptions and query engine are never stored, shown or used: only
article-to-article edges leave the build, with the shared entity names as
`evidence` (ADR-0002). The request path makes no model call for expansion.

**5. `mentions.jsonl` is the extractor-neutral contract.** The build exports
raw (entity, type, article slug) rows; scoring (allowed types, aliases,
stoplist, hub cut, `ln(N / df)` per shared entity) reads only that file. The
extractor can be replaced by touching the exporter alone, and a policy change
needs no re-extraction.

**6. LightRAG is chosen without the planned spike.** The spike (LightRAG
against Microsoft GraphRAG on the same 100 articles) needs live model runs;
it becomes a check run later (`build --sample 100`). GraphRAG stays the
alternative behind decision 5.

**7. One per-seed cap serves every source.** `LINK_EXPANSION_MAX_LINKS_PER_SEED`
(20) was tuned for authored links, most of which link far fewer pages; an
entity-graph seed will nearly always fill it. Its value for `entity_graph` is
an eval variable (3, 5, 10), chosen with the source in the eval runs, and each
run reports the cross-encoder's batch as the `pool_size` retrieval signal,
which nothing scores.

## Rationale

The table is what lets a KB without links get expansion at all, and it moves
link extraction from every ticket to ingestion. Keeping each source's rows
tagged lets an eval switch from one source to another, links withheld,
without editing the KB. Holding the extractor to an offline job and to
article-to-article edges keeps every boundary where an earlier ADR put it:
ai-engine still writes nothing (it hands core-api a file), no generated text
reaches a requester, and the scores a threshold sees are unchanged.

## Alternatives considered

- **LightRAG or GraphRAG as a retriever inside RRF.** Their query engines
  generate text and would need their own scores calibrated; out of scope.
- **Ticket-chosen links** (weight each shared entity by its similarity to the
  ticket at request time). Better in principle, since stored pairs are the
  same for every ticket; a later experiment (R3q) once stored pairs exist.
- **Skip inactive targets at write time.** Simpler rows, but every
  reactivation would need a rebuild or rescore; rejected for decision 2.
- **A separate cap per source.** Possible later; the eval sweep comes first.
- **Following several sources at once.** Their scores can't be ranked
  together; left until one source has been chosen on its own merits.

## Consequences

- `ai_engine_ro` reads one more table. `tests/test_db_tables.py` pins it.
- A new article's incoming authored links appear at the next full
  `build_associations --source authored_link` (or `load_demo_kb`).
- Re-ingesting an article drops its `entity_graph` and `embedding_neighbour`
  rows in both directions until the next build, so it runs on its authored
  links meanwhile.
- The ai-engine regex link path stays, parity-only, until the parity check
  has been run against the loaded demo KB.

## Before this is accepted

1. **Parity:** for every active demo-KB article, the table path returns the
   same links as the regex path, and R1's recall@3 matches the last full run.
2. **Spike check:** `build --sample 100`, with a hand check of 20 entities and
   `ASSOCIATION_HUB_DF_MAX` chosen from the df histogram.
3. **Eval runs R0-R3** (the plan's gates), one source each: `entity_graph`
   beats `embedding_neighbour`, loses no ticket against R0 (no expansion),
   adds no auto-reply false positive against R1 (`authored_link`), keeps
   refusal and injection, and reports `pool_size`.

## Amendment, 2026-10-10: the `remedy_pointer` source

The full entity graph scored recall@3 0.817 against authored links' 0.917,
and a local stage check (`evals/HISTORY.md` 2026-10-10 (5)) found why: 7 of
its 11 misses never reach the pool, because the page that fixes the ticket
shares few non-hub entities with the page that points to it. Support
tickets need a pointer ("to remediate, see ..."), which shared vocabulary
does not express.

A fourth source, `remedy_pointer`, extracts that relation directly. Per
page section, DeepSeek lists (symptom, remedy, where the remedy is written:
this page or a page the text names), under a versioned policy
(`core/prompts/kb_remedies.v*.yaml`). A named page resolves to a KB page by
exact title or heading, then by embedding above
`REMEDY_RESOLVE_MIN_SIMILARITY`; anything else is dropped and counted. An
edge A -> B means page A names a problem whose fix is on page B, scored by
the number of distinct pairs pointing that way. Links are stripped to their
text before extraction, so the graph is what the prose says, as a KB with
no hyperlinks would give it: authored links are not copied in.

It does not use LightRAG: one JSON call per section, replies cached by
content, so a rebuild sends only changed sections. That supersedes the
"commit to LightRAG" choice for this source only; `entity_graph` keeps it.
It is compared with the other sources one at a time, like them.
