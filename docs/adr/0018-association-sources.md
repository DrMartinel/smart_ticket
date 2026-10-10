# ADR-0018: Association sources for link expansion: authored links or an entity graph

**Status:** Proposed. Both sources are built and measured
(`evals/HISTORY.md` 2026-10-08 to 2026-10-10); awaiting review.
**Date:** 2026-10-07, simplified 2026-10-10
**Builds on:** ADR-0014 decision 1 (an article-associations layer feeds
candidate expansion) and its *Before this is accepted* #3 (a KB-agnostic
association source)
**Touches:** ADR-0004 (ai-engine's read-only role: one more SELECT grant),
ADR-0002 (auto-reply quotes approved KB text only), ADR-0005 / ADR-0015 (which
score a threshold may see), ADR-0019 (DeepSeek for evaluation)

## Context

Link expansion (ADR-0014) follows the Markdown links of the articles behind
the cross-encoder's top 3 chunks, and on the demo KB that recovers misses
nothing else does. It has two limits:

1. **It only works on a KB that links its pages.** An internal KB of
   hand-written runbooks, PDFs or ticket history often has no links at all.
2. **It extracted links per request**, regex over every seed's chunk text on
   every ticket, because there was no table to read them from.

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

**3. Two sources; a deployment follows exactly one, `ASSOCIATION_SOURCE`**
(`authored_link`, `entity_graph`, or `none` to turn expansion off). Their
scores are on different scales, so they are never followed together.

| Source | Built by | Model calls |
|---|---|---|
| `authored_link` | core-api, at ingest and by `build_associations --source authored_link` | none |
| `entity_graph` | ai-engine's offline build, loaded by core-api's `load_associations` | offline only, never per ticket |

**4. The entity graph is a graph of pointers from a problem to its fix.**
Per page section (up to `ENTITY_GRAPH_SECTION_TOKENS`), DeepSeek lists
(symptom, remedy, where the remedy is written: this page, or a page the text
names), under a versioned prompt (`core/prompts/kb_entity_graph.v*.yaml`).
Links are stripped to their text first, so the graph is what the prose says,
as a KB without hyperlinks would give it. A named page resolves to one KB
page by exact title or H1/H2 heading, then by embedding above
`ENTITY_GRAPH_RESOLVE_MIN_SIMILARITY`; a name matching several pages, or
none, is dropped and counted, never guessed. An edge A -> B means page A
names a problem whose fix, the text says, is on page B; its score is the
number of distinct (symptom, remedy) pairs pointing that way, and its
`evidence` is those pairs (ADR-0002: never shown to a requester).

**5. The build runs offline, on DeepSeek, and writes no row.** One JSON call
per section, replies cached by (prompt version, model, section budget,
section text), so a rebuild sends only new or changed sections; a failed
section exports nothing and is all a re-run asks for. It hands core-api
`entity_graph.jsonl` (ADR-0004), with `entity_graph_pairs.jsonl` and
`entity_graph_resolutions.jsonl` beside it for review. DeepSeek is used for
evaluation only, on KB text, never ticket text (ADR-0019).

**6. One per-seed cap serves both sources.** `LINK_EXPANSION_MAX_LINKS_PER_SEED`
(20). An entity-graph page names few fix pages (2.3 on average), so the cap
rarely binds; each run reports the cross-encoder's batch as the `pool_size`
retrieval signal, which nothing scores.

## Rationale

The table is what lets a KB without links get expansion at all, and it moves
link extraction from every ticket to ingestion. The pointer graph targets
the relation support tickets need, "for this problem, the fix is on that
page". On the demo KB, from prose alone, it scores recall@3 0.900 against
authored links' 0.917, at a pool of 21 chunks at the median against 51
(`evals/HISTORY.md` 2026-10-10 (6)). With one chunk per page in Jev's top 3
it tied authored links at 0.917 and a full run passed every gate
(2026-10-10 (7), (8)); that limit has since been removed, so those two
results no longer describe the shipped pipeline.

## Alternatives considered

- **A shared-entity graph (LightRAG).** Extracted entities per article and
  linked pages by rare shared entities. Built over the full KB: recall@3
  0.817. A stage check found why (2026-10-10 (5)): the page that fixes a
  ticket shares few non-hub entities with the page that points to it, and no
  hub cut brought the fix pages within reach. Removed.
- **Embedding neighbours between articles.** No model, no links: recall@3
  0.800 (2026-10-08, R2). Removed.
- **LightRAG or GraphRAG as a retriever inside RRF.** Their query engines
  generate text and would need their own scores calibrated; out of scope.
- **Following both sources at once.** They miss different tickets (authored
  links g056, the entity graph g050), but their scores can't be ranked
  together; it would need its own rule, evaluation and decision.

## Consequences

- `ai_engine_ro` reads one more table. `tests/test_db_tables.py` pins it.
- A new article's incoming authored links appear at the next full
  `build_associations --source authored_link` (or `load_demo_kb`).
- Re-ingesting an article drops its `entity_graph` rows in both directions
  until the next build, so it runs on its authored links meanwhile.
- The ai-engine regex link path stays, parity-only, until it is deleted
  (`docs/TODO.md` item 12).

## Before this is accepted

1. Review of the measurements in `evals/HISTORY.md` 2026-10-08 to 2026-10-10.
2. A choice of the shipped source for the demo KB (today `authored_link`).
