# Refactor checklist

`/refactor` checks every change against this list: the moves it applies, and any
diff the user asks it to check. Add items with `/checklist-add`; don't hand-edit
the numbering.

Each item has a severity:
- **[regression]**: breaks a hard rule or safety invariant. Fix before merge.
- **[convention]**: house style. Fix, or say why not.

An item is **pass**, **fail** (with `file:line`) or **n/a** (the diff touches
nothing it covers). Only code the diff adds or changes is checked; older code is
listed under "outside the diff", never failed.

---

## Comments and docstrings

### C-01 [convention] Comments and docstrings say what, in one plain sentence
- **Check:** every comment or docstring the diff adds or changes says what the
  file, class or function does. No inputs or outputs (the signature has them), no
  why, no how. A test docstring, if any, says what the test checks.
- **Violation:** `"""Replaces the rows; returns (written, skipped)."""`,
  `# A sample's edges are a spike's, never the KB's: writing them would ...`
- **Fix:** `"""Replaces the `entity_graph` rows with `rows`."""`
- **Source:** CLAUDE.md *Comments and docstrings*; readability.md §2–3

### C-02 [regression] A removed reason is recorded somewhere else
- **Check:** when the diff deletes or trims a comment that gave a reason
  (especially a silent failure it named), that reason is in an ADR or
  `load-bearing.md`, or the diff adds it there.
- **Violation:** deleting `# Order by the raw distance, not by score: ... the HNSW
  index can serve` with no `load-bearing.md` entry.
- **Fix:** add the `load-bearing.md` entry in the same commit.
- **Source:** CLAUDE.md *Comments and docstrings*; moves.md #10

### C-03 [convention] Tests are named for the failure mode they prevent
- **Check:** each new test's name says what goes wrong if it fails.
- **Violation:** `test_build_2`, `test_write_rows`
- **Fix:** `test_a_failed_write_exits_1`, `test_a_sample_writes_no_row`
- **Source:** CLAUDE.md *Testing conventions*

## Where logic goes

### C-04 [convention] Each piece of core-api logic is in the layer that owns it
- **Check:** `views.py` only takes the schema, calls one function or method and
  returns; schemas check shape with no database access; model methods are rules
  about one row; queryset/manager methods choose rows; work across models,
  transactions and side effects is a method on a service class in `utils`.
- **Violation:** a handler that loops over models and writes; a manager method
  that writes `AuditLog` and queues a task.
- **Fix:** move the work onto a `utils` service class the handler calls.
- **Source:** CLAUDE.md *Where logic goes* rule 1

### C-05 [convention] Model methods stay pure-ish
- **Check:** a model method the diff adds or changes doesn't touch `request`,
  write to another model, call ai-engine/HTTP/Celery/email, or query inside a
  `@property`.
- **Violation:** `KbArticle.ingest` calling `ai_engine.embed(...)`.
- **Fix:** a method on a `utils` service class that does the call and the writes.
- **Source:** CLAUDE.md *Where logic goes* rule 5

## Functions and classes

### C-06 [convention] Extracted by meaning, not by use count
- **Check:** no new 1–3 line function with one caller whose name restates its
  body; no extracted function that needs more than 3 arguments passed through.
- **Violation:** `def model_id(): return f"deepseek:{settings.cloud_model}"` with
  one caller; `def main(argv): return cls(cls.parse_args(argv)).run()`.
- **Fix:** inline it at the caller.
- **Source:** CLAUDE.md *Where logic goes* rule 2

### C-07 [convention] A private `_helper` is the last resort
- **Check:** before a new `_helper`, the diff considered, in order: is it about
  one row (model method)? About which rows (queryset method)? Neither: a method on
  the class that owns the data or the work (in core-api, a service class in
  `utils`), named as a domain action. A new module-level function is a fail
  unless its work is generic, tied to no use case or model (building a regex,
  finding a pattern in a string: `normalize_ws` in `validate.py`).
- **Violation:** `_discount(coupon, subtotal)`, a private helper computing one
  coupon's discount.
- **Fix:** `coupon.discount_for(subtotal)`, a model method.
- **Source:** CLAUDE.md *Where logic goes* rule 3

### C-08 [convention] A class earns its place
- **Check:** each new class holds state or groups several behaviours around one
  thing. One with a single public method hasn't earned it.
- **Violation:** `class EntityGraphStore` whose only method is `replace`.
- **Fix:** `replace` becomes a method of the class that owns that work, and
  `EntityGraphStore` goes.
- **Source:** CLAUDE.md *Where logic goes* rule 4

### C-09 [convention] No data held or derived twice
- **Check:** no second record type, dict or method that rebuilds what an object
  already holds (an id→slug map next to articles that carry both, a list of slugs
  next to the pages, a method returning `{a.slug: a.id ...}` for one caller).
- **Violation:** `Article` without `title` plus a `titles` dict and a `pages()`
  method to glue them; `slug_of[source.id]` where `source.slug` exists.
- **Fix:** one record with every field; read the attribute directly.
- **Source:** this checklist (2026-10-13 review of `core/associations/`)

### C-10 [convention] No dependency-injection plumbing for a module singleton
- **Check:** no new parameter or attribute that only passes along a module
  singleton (`db`, `embedder`, `shortlister`). Tests swap the singleton with
  `monkeypatch.setattr(module, "db", fake)`.
- **Violation:** `def __init__(self, ..., database=None): self._db = database or db`
- **Fix:** call `db.all(...)` / `db.write(...)` directly.
- **Source:** readability.md §6 (commit 55e853b)

### C-11 [convention] Construction does no I/O
- **Check:** `__init__` takes data and opens no connection; a read from the
  database or a file is a separate classmethod constructor.
- **Violation:** `KbSnapshot.__init__` running the `SELECT`.
- **Fix:** `KbSnapshot.read()` reads and calls `cls(articles)`.
- **Source:** readability.md §6

### C-12 [convention] A singleton is built once, at import
- **Check:** an object the diff builds from settings alone (no per-call data) is
  created once as a module-level instance at the bottom of its module, under a
  `# --- <what> ---` divider, not inside a function or method on every call.
  Building it opens no socket, so the import stays safe.
- **Violation:** `decision = Router(settings.THRESHOLDS).route(signals, None, None)`
  inside `pipeline.py`'s per-ticket run.
- **Fix:** `router = Router(settings.THRESHOLDS)` once at import (as
  `db = SqlAlchemySessionSource()` in `ai_engine/core/db/client.py`), then
  `router.route(signals, None, None)`.
- **Source:** readability.md §1.5, §6, §8
