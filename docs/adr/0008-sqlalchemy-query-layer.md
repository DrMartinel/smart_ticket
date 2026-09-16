# ADR-0008: ai-engine builds its read queries with SQLAlchemy 2.0

**Status:** Accepted
**Date:** 2026-09-16

## Context

ai-engine runs four read queries: BM25 and vector retrieval over `kb_chunks`,
nearest-neighbour few-shot selection over `fewshot_examples`, and the
log-only KB policy lookup on `kb_articles`. All four were SQL strings passed
straight to psycopg, with embeddings serialized into `'[...]'::vector`
literals by hand.

ADR-0007 rejected a LangChain vectorstore for the DB seam partly because it
"would hide the raw SQL" that the `ai_engine_ro` SELECT-only grant model
(ADR-0004) is written against. Moving off raw SQL has to answer that
objection rather than step around it.

## Decision

Queries are built with SQLAlchemy 2.0 against partial declarative table
classes in `core/db/tables.py`. psycopg 3 remains the driver. The session
source lives beside them in `core/db/client.py` and is still constructed only
by `build_providers()`.

| Concern | Owner |
|---|---|
| The schema (columns, types, constraints, grants) | core-api's Django models + `infra/migrations/sql/` — unchanged |
| Which columns ai-engine may reference | `core/db/tables.py`, only the columns actually queried |
| The query shape | built inline where it runs, as a SQLAlchemy `select()` |
| Result types | unchanged — `VectorHit`, `LexicalHit`, plain dicts |
| Enforcement of read-only | the `ai_engine_ro` role — unchanged |

`VectorHit` and `LexicalHit` are **not** mapped classes. They are search
results — a join plus a per-query score — and making them ORM entities would
bring session tracking and detached-instance errors for no gain. Every query
selects columns, never entities, so results are plain rows.

## Rationale

### Why this does not reopen ADR-0007's objection

The objection was about *hiding* the SQL. A vectorstore decides the query for
you. Here every statement is written out in this repo, compiles to SQL that
can be printed, and is pinned by `tests/test_db_queries.py`, which runs each
real query path and reads the statement the session fake recorded: the
retracted / expired few-shot filters, the `IS NOT NULL` embedding filters, the
`'simple'` text-search config, and the bare `<=>` in `ORDER BY` that the HNSW
index needs. Previously nothing asserted any of those — the cursor fakes answered
by rows and never read the SQL.

### Why tables are declared partially

A full declaration would be a second schema that drifts from core-api's.
Declaring only referenced columns means an unrelated column change in
core-api needs no edit here, and a renamed referenced column fails exactly
as loudly as it did in a SQL string.

### Why the boundary is also pinned in code

`tests/test_db_tables.py` fails if a table outside the ADR-0004 grant is
declared, or if `create_all` / `session.add` / `commit` / ... appears in
ai-engine. The role would reject both at runtime, but the policy lookup
swallows every exception into deny-by-default, so a runtime rejection there
would be silent.

## Consequences

### Accepted: embeddings go over the wire as text again

`pgvector.sqlalchemy.VECTOR` serializes to the `'[...]'` text form. The
brief binary path (`register_vector`) is gone. For a 1024-dim query vector
sent once or twice per ticket this is noise next to the embedding call and
the cross-encoder.

### Accepted: a new dependency

`sqlalchemy` (plus `greenlet`). Small next to torch.

### Accepted: the BM25 query reads worse

Full-text search has no SQLAlchemy operators: `@@` is a `bool_op`,
`plainto_tsquery` and `ts_rank_cd` are `func` calls.

### Gained: the SQL is under test

See above. The policy query in particular was unobservable when broken.

### Gained: a single driver-URL fix

`SqlAlchemySessionSource` rewrites `postgresql://` to `postgresql+psycopg://`,
so `DATABASE_URL` keeps the form docker-compose, CI and evals already use.
Without it SQLAlchemy would pick psycopg2, which is not installed, and
`create_engine` would fail at boot. Installing psycopg2 instead was rejected:
it would silently become ai-engine's driver while core-api stays on psycopg 3.

## Alternatives considered

**Keep raw SQL, adopt only `pgvector.psycopg`.** Removes the hand-rolled
vector literal and sends embeddings in binary, but leaves the SQL unasserted.
It was the state immediately before this change.

**SQLModel.** Briefly adopted, then removed. Its value is one class serving as
both table and validated Pydantic model, which ai-engine never uses: queries
select columns, not instances, and `table=True` classes skip validation
anyway. Every type we need (`VECTOR`, `TSVECTOR`, `JSONB`) went through its
`sa_column=` escape hatch to SQLAlchemy, and it is a pre-1.0 (0.0.x) layer
over a library we depend on directly regardless.

**SQLAlchemy Core with `table()` / `column()`.** Equivalent queries without
`MetaData`, so `create_all` is not even reachable. Rejected in favour of
declarative classes for readability alongside core-api's Django models;
`test_db_tables.py` covers the `create_all` risk instead.

**Reflecting tables at startup.** Needs a connection before the graph is
built, which breaks `build_providers()`'s no-socket-at-construction contract.
