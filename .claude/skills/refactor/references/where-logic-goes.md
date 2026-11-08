# Where logic goes

Where each piece of core-api logic lives: the layer that owns it, when to
extract, when a class earns its place, and the code that predates these rules.
The summary is in `CLAUDE.md` *Where logic goes*; these rules sit under its hard
rules. `checklist.md` C-04 to C-08 check a diff against them.

Logic lives with the data it describes: rules about one row go on the model,
which rows count goes on the queryset, and work across several models goes
in a service class. Endpoints and schemas stay thin.

**1. Each piece goes in the layer that owns it.** Inside core-api, each app has:

| Layer | Module | Owns | Example |
|---|---|---|---|
| Endpoint | `views.py` | HTTP only: take the request schema, call a service class, model or queryset method, return the result with `response=` | a handler that validates the body and makes one call |
| Schema | `request_schema.py` / `response_schema.py` | Shape and field checks; no database access. No handler builds a response dict | `subject: str = Field(min_length=3, max_length=200)` |
| Model method | `models.py` | Rules about **one row**, from its own fields plus arguments | `article.chunks_are_current()` |
| QuerySet method | `models.py` | **Which rows** count | `ReviewItem.objects.for_queue(...)`, `FewshotExample.objects.active_for_category(...)` |
| Service class | `utils.py` or `utils/` (this repo's `services.py`) | Work across several models, transactions, and side effects (ai-engine calls, Celery, email) | the per-ticket run in `pipeline.py` (module functions today, see below) |
| Pure decision | `utils/` | A decision with no I/O | `router.py` (CLAUDE.md hard rule 1), `trust_scorer.py`, `masking.py` |
| Task | `tasks.py` | Celery entry points only; the work lives in services | `process_ticket` |

**2. Extract by meaning, not by how often code is used.** Extract a block
when it is a named business rule, has its own edge cases, or deserves its
own test. Inline it when the body is 1–3 obvious lines and the name would
restate them. If an extracted function needs more than 3 arguments passed
through, the cut is wrong: move the boundary or inline it.

**3. A private `_helper` is the last resort.** Before writing one, ask in
order: is it about one row (model method)? About which rows (queryset
method)? Otherwise, a method on the class that owns the data or the work (in
core-api, a service class in `utils`), named as a domain action. A module-level
function only for generic work tied to no use case or model, such as building a
regex or finding a pattern in a string (`normalize_ws` in `validate.py`).

**4. A class has to earn it.** Use one when it holds state or groups several
behaviours around one thing. A class with a single public method
(`OrderService.create()`) hasn't earned one: its method goes on the class that
owns that data or work (rule 3).

**5. Model methods stay pure-ish.** They don't touch `request`, write to
other models, call external systems (ai-engine, HTTP, Celery, email), or run
queries inside a `@property` (one extra query per row in a loop). Those go in
service classes.

Code that predates these rules:
- Model methods that break rule 5: `KbArticle.set_auto_reply_allowed` and
  `set_risk_tier` (write `KbAuthorityLog`), `ReviewItem.decide` (writes
  `ReviewDecision`, `EvalCandidate`).
- Manager methods that write, which rule 1 puts in service classes:
  `KbArticle.objects.create_and_ingest` / `upsert_from_source`,
  `Incident.objects.get_or_create_for_mass_incident`,
  `AuditLog.objects.record`.

- `utils/pipeline.py` and the other `utils` modules: use-case module-level
  functions, which rule 3 puts on a service class.

Move each to a service class when you next change it, keeping every
write in its current transaction (the authority log row is ADR-0002).

`apps/core` is the shared foundation: abstract `BaseModel`, middleware,
ops commands (`wait_for_db`), generic test helpers. Every app may import
from it; it imports from no app (`apps/core/tests/test_boundary.py`).
The route gate (`require(Permission…)`, `AuthedRequest`) lives in
`apps/accounts/permissions.py`, beside the `User` and the `Access` it checks;
it can't live in `core`, which may not import `accounts`. Beside `apps/` sit
`infrastructure/` (the ai-engine client, with its wire schema in `dtos.py`) and
`config/settings/{base,development,production,test}.py`. Tests live in a
`tests/` package next to the code they test.
