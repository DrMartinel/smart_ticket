# ADR-0011: UUID primary keys on every business table

**Status:** Accepted
**Date:** 2026-09-29
**Departs from:** spec §3 DDL (`BIGSERIAL PRIMARY KEY` on every table)

## Context

Every table used an auto-incrementing `bigint` key, as the spec's DDL has
it. Two things made that awkward:

- Django adds the `id` column at runtime, so pyright could not see it. Every
  model carried a bare `id: int` annotation purely for the type checker.
- Sequential ids leak volume and are guessable: `/review/items/41` says there
  were 40 before it, and invites trying 42.

## Decision

Every model in core-api declares its key explicitly:

```python
id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
```

(Since then declared once, on the abstract `apps.core.models.BaseModel` that
every model inherits. Same column, no migration.)

- **Version 4** (random, stdlib `uuid.uuid4`). Version 7 would keep new rows
  in insert order in the primary-key index, but Python 3.13 has no
  `uuid7()` and it was not worth a new dependency yet. Revisit if insert
  speed on `audit_log` or `ai_runs` becomes a problem.
- **All tables**, including `User`, KB articles and chunks. `TicketEmbedding`
  is keyed by its ticket and `PiiQuarantine` already had a UUID `ref`.
- **The `0001_initial` migrations were regenerated**, not converted in place.
  An existing database has to be dropped and re-seeded (`seed_demo`). This
  was acceptable only because the project is pre-release with no real data.

`DEFAULT_AUTO_FIELD` stays `BigAutoField`: Django's own auto-created tables
(the user-to-group link table) need an integer key. Because of that, a new
model that forgets its `id` line silently gets a bigint key.
`apps/dbextras/tests/test_primary_keys.py` fails if any model in our apps is
not keyed by a UUID.

## Consequences

- Ids are strings in JSON: API responses, the web client's types, and the
  ai-engine wire (`retrieved_chunks[].chunk_id`, `KBArticleMeta.id`).
- Celery task arguments are passed as `str(ticket.id)`, because task
  arguments go through Celery's JSON serializer.
- ai-engine's prompt context names each chunk `chunk_id=<uuid>` instead of a
  small integer. That is more tokens per chunk and changes what the model
  sees; the live eval suites should be run before this ships.
- `<fk>_id` attributes were still invisible to pyright, so a model that read
  one declared it. (Superseded by the move to mypy + django-stubs, whose plugin
  infers them; those declarations were removed.)
