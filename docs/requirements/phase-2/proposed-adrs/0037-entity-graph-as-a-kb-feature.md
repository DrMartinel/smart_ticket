# ADR-0037: The entity graph survives edits, rebuilds on a schedule, and takes editor overrides

**Status:** Proposed (phase 2 pack, stage 4). Copied to [`docs/adr/0037-entity-graph-as-a-kb-feature.md`](../../../adr/0037-entity-graph-as-a-kb-feature.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** ADR-0014, ADR-0018, ADR-0025 (ai-engine writes its edges), ADR-0019
**Feature:** F11 ([spec](../06-F11-graph-retrieval.md))

## Context

Re-ingesting a page deletes its `entity_graph` edges; only a manual CLI run
restores them. F6 makes edits routine, so pages would drop out of link
expansion after every edit. Editors can't see or correct edges.

## Decision

1. **Re-ingest marks edges `stale`** instead of deleting them, and files a
   rebuild request.
2. **A scheduled job runs ai-engine's build CLI with `--pending`** every 15
   minutes. It stays an offline build (ADR-0025's scope); no new HTTP endpoint
   writes to the database.
3. **Editor corrections live in `kb_association_overrides`** (`hide`, `add`),
   written by core-api and only read by ai-engine. Builds never touch them, so
   they survive rebuilds.
4. **`ai_engine_ro` gets SELECT on the overrides table** and limited UPDATE on
   the rebuild-request table. No other grant changes.
5. Scores and evidence still never reach a threshold, the trust score, the
   router, or a requester.

## Consequences

- An edited page keeps expanding through its old edges for at most one build
  interval.
- A second table joins the link query; the retrieval eval gate must pass
  unchanged with no overrides present.
