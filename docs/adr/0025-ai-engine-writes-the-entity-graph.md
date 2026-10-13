# ADR-0025: ai-engine writes the entity graph's rows

**Status:** Accepted (2026-10-13), the owner's decision
**Date:** 2026-10-13
**Supersedes:** ADR-0004 reason 1 (`ai_engine_ro` SELECT-only), for one
table: `kb_article_associations`. Every other table keeps ADR-0004's grants.
**Amends:** ADR-0018 decision 5 (the build writes no row; core-api loads
its file)

**This relaxes a guardrail.** ADR-0004's boundary was that ai-engine could
not write to the database at all, whatever its code did. After this ADR,
`ai_engine_ro` can insert and delete rows in one table, and ai-engine's own
code, not Postgres, is what keeps triage from using that.

## Context

The `entity_graph` association source (ADR-0018) is built offline by
ai-engine and reached the database in three steps: `build.py` wrote
`entity_graph.jsonl`, the file was committed, and core-api's
`load_associations` loaded it, alone or inside `load_demo_kb`. Building
new edges and having triage follow them took two commands in two services,
and a forgotten load left a new build unused, silently. The owner chose to
have the build write its own rows.

## Decision

1. **`ai_engine_ro` gets INSERT and DELETE on `kb_article_associations`**
   (`infra/migrations/sql/0006_association_grant.sql`, edited in place, so a
   database migrated before 2026-10-13 needs its volume reset or the GRANT
   run by hand). No UPDATE: a build replaces its rows and never edits one.
   No write on any other table.
2. **Only the offline build writes, and only `entity_graph` rows.**
   `build.py` replaces every row with `source = 'entity_graph'` in one
   transaction (`db.write`), so link expansion reads the old graph or the
   new one, never neither. `authored_link` rows stay core-api's.
   `--sample` writes no row; `--rescore-only` writes the rows from the
   committed pairs with no model call, which is how a fresh database gets
   its edges.
3. **`load_associations` is removed.** `entity_graph.jsonl` is still written
   and committed: it is what a reviewer reads in the PR.
4. **The role keeps its name.** `ai_engine_ro` is no longer read-only on
   that table; renaming it would touch the role migration, `.env.example`,
   compose and every `.env` for no change in what it can do.

## What still holds

- Triage writes nothing. `tests/test_db_tables.py` fails if anything but
  `core/associations/build.py` calls `db.write` or builds an
  insert/update/delete statement, and core-api's
  `test_associations_grant.py` fails if the role can UPDATE the table or
  write any other one (tickets, routing decisions, AI runs, the audit log,
  the KB itself).
- An association's `score` only orders a seed's targets (ADR-0005); no
  threshold, trust feature or router input reads it.
- core-api still drops an edited article's `entity_graph` edges
  (`ArticleIndexer.ingest`): edges from old text must not
  outlive it.

## Consequences

- The build needs the database credentials it already had, with more
  rights; anyone holding `AI_ENGINE_DATABASE_URL` can now delete every
  entity-graph edge. The running ai-engine service holds the same
  credentials.
- After `make load-demo-kb`, run `build --rescore-only` (demo_kb/README.md)
  or link expansion on `ASSOCIATION_SOURCE=entity_graph` finds no edges.
